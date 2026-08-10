import csv
import json
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.db.models import Avg, Max, Min
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import SmartBin, TelemetryRecord

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

GAS_ANOMALY_THRESHOLD = 600
COMMAND_TIMEOUT_SECONDS = 30
HISTORY_SAMPLE_SECONDS = 30


def auth_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard_home')
    return render(request, 'home/auth.html')


def login_action(request):
    if request.method == 'POST':
        user = authenticate(
            request,
            username=request.POST.get('username'),
            password=request.POST.get('password'),
        )
        if user is not None:
            login(request, user)
            return redirect('dashboard_home')
        return render(request, 'home/auth.html', {'login_error': 'Invalid username or password.'}, status=401)
    return redirect('auth_view')


def register_action(request):
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        if len(username) < 3 or len(password) < 8:
            return render(request, 'home/auth.html', {
                'register_error': 'Use at least 3 characters for the username and 8 for the password.'
            }, status=400)
        if User.objects.filter(username=username).exists():
            return render(request, 'home/auth.html', {'register_error': 'That username is already registered.'}, status=409)
        User.objects.create_user(username=username, password=password)
        user = authenticate(request, username=username, password=password)
        login(request, user)
        return redirect('dashboard_home')
    return redirect('auth_view')


def logout_action(request):
    logout(request)
    return redirect('auth_view')


def _dashboard_context():
    bins = list(SmartBin.objects.all())
    online_count = sum(1 for b in bins if b.is_online)
    return {
        'bins': bins,
        'total': len(bins),
        'online': online_count,
        'offline': len(bins) - online_count,
        'bins_full_count': sum(1 for b in bins if b.binFull),
        'gas_anomalies': sum(1 for b in bins if b.gas_value > GAS_ANOMALY_THRESHOLD),
        'critical_bins': [b for b in bins if b.alert_status != 'NOMINAL'],
        'avg_fill': round(sum(b.fill_level for b in bins) / len(bins), 1) if bins else 0,
        'avg_gas': round(sum(b.gas_value for b in bins) / len(bins), 1) if bins else 0,
    }


@login_required(login_url='auth_view')
def dashboard_home(request):
    context = _dashboard_context()
    context['snapshot_chart'] = json.dumps([
        {'device': b.device_id, 'fill': b.fill_level, 'gas': b.gas_value}
        for b in context['bins']
    ])
    return render(request, 'home/dashboard.html', context)


@login_required(login_url='auth_view')
def dashboard_stats_fragment(request):
    return render(request, 'home/_dashboard_stats.html', _dashboard_context())


@login_required(login_url='auth_view')
def dashboard_table_fragment(request):
    return render(request, 'home/_dashboard_table.html', _dashboard_context())


def _period_days(request, default=7):
    try:
        days = int(request.GET.get('days', default))
    except (TypeError, ValueError):
        days = default
    return days if days in (1, 7, 30, 90) else default


def _system_analytics(days=7):
    since = timezone.now() - timedelta(days=days)
    records = TelemetryRecord.objects.select_related('smart_bin').filter(recorded_at__gte=since).order_by('recorded_at')
    buckets = defaultdict(lambda: {'fill': [], 'gas': [], 'temperature': []})
    alert_counts = {'NOMINAL': 0, 'BIN_FULL': 0, 'METAL': 0}

    for rec in records:
        key = timezone.localtime(rec.recorded_at).strftime('%d %b %H:00') if days <= 7 else timezone.localtime(rec.recorded_at).strftime('%d %b')
        buckets[key]['fill'].append(rec.fill_level)
        buckets[key]['gas'].append(rec.gas_value)
        buckets[key]['temperature'].append(rec.temperature)
        alert_counts[rec.alert_status] = alert_counts.get(rec.alert_status, 0) + 1

    trend = []
    for label, vals in buckets.items():
        trend.append({
            'label': label,
            'fill': round(sum(vals['fill']) / len(vals['fill']), 1),
            'gas': round(sum(vals['gas']) / len(vals['gas']), 1),
            'temperature': round(sum(vals['temperature']) / len(vals['temperature']), 1),
        })

    return trend[-120:], alert_counts, records.count()


@login_required(login_url='auth_view')
def system_status(request):
    bins = list(SmartBin.objects.all())
    online = sum(1 for b in bins if b.is_online)
    days = _period_days(request)
    trend, alert_counts, sample_count = _system_analytics(days)
    context = {
        'bins': bins,
        'total': len(bins),
        'online': online,
        'offline': len(bins) - online,
        'critical_count': sum(1 for b in bins if b.alert_status != 'NOMINAL'),
        'days': days,
        'sample_count': sample_count,
        'trend_json': json.dumps(trend),
        'alert_json': json.dumps([
            {'label': 'Nominal', 'value': alert_counts.get('NOMINAL', 0)},
            {'label': 'Bin full', 'value': alert_counts.get('BIN_FULL', 0)},
            {'label': 'Metal detected', 'value': alert_counts.get('METAL', 0)},
        ]),
        'device_snapshot_json': json.dumps([
            {'device': b.device_id, 'fill': b.fill_level, 'gas': b.gas_value}
            for b in bins
        ]),
    }
    return render(request, 'home/status.html', context)


def _resolve_command_status(smart_bin):
    if smart_bin.last_command_status == 'PENDING' and smart_bin.last_command_time:
        elapsed = (timezone.now() - smart_bin.last_command_time).total_seconds()
        if elapsed > COMMAND_TIMEOUT_SECONDS:
            smart_bin.last_command_status = 'TIMEOUT'
            smart_bin.save(update_fields=['last_command_status'])
    return smart_bin


def _device_history_payload(smart_bin, days):
    """Return selected-period telemetry, or the last stored reading when none exists.

    Keeping the last known point means analytics remain informative while a device is
    offline or when its latest sample falls outside the selected time window.
    """
    since = timezone.now() - timedelta(days=days)

    # Take the newest 500 samples in the selected window, then display oldest -> newest.
    recent_desc = list(
        smart_bin.telemetry_records
        .filter(recorded_at__gte=since)
        .order_by('-recorded_at')[:500]
    )
    records = list(reversed(recent_desc))
    using_last_known = False

    if not records:
        latest_record = smart_bin.telemetry_records.order_by('-recorded_at').first()
        if latest_record is not None:
            records = [latest_record]
            using_last_known = True

    if records:
        history = [{
            'label': timezone.localtime(r.recorded_at).strftime('%d %b %H:%M'),
            'fill': r.fill_level,
            'gas': r.gas_value,
            'temperature': r.temperature,
            'humidity': r.humidity,
            'elementTemp': r.element_temp,
            'lastKnown': using_last_known,
        } for r in records]
        last_known_at = records[-1].recorded_at
    else:
        # Very first device registration may predate the history table. Use the current
        # persisted SmartBin values so the graph still has a truthful last-known point.
        history = [{
            'label': timezone.localtime(smart_bin.last_seen).strftime('%d %b %H:%M'),
            'fill': smart_bin.fill_level,
            'gas': smart_bin.gas_value,
            'temperature': smart_bin.temperature,
            'humidity': smart_bin.humidity,
            'elementTemp': smart_bin.elementTemp,
            'lastKnown': True,
        }]
        using_last_known = True
        last_known_at = smart_bin.last_seen

    return history, len(recent_desc), using_last_known, last_known_at


@login_required(login_url='auth_view')
def device_detail(request, bin_id):
    smart_bin = _resolve_command_status(get_object_or_404(SmartBin, id=bin_id))
    days = _period_days(request)
    history, sample_count, using_last_known, last_known_at = _device_history_payload(smart_bin, days)

    context = {
        'bin': smart_bin,
        'days': days,
        'history_json': json.dumps(history),
        'sample_count': sample_count,
        'using_last_known': using_last_known,
        'last_known_at': last_known_at,
        'telemetry_endpoint': request.build_absolute_uri('/api/telemetry/'),
    }
    return render(request, 'home/device_detail.html', context)


@login_required(login_url='auth_view')
def device_live_fragment(request, bin_id):
    smart_bin = _resolve_command_status(get_object_or_404(SmartBin, id=bin_id))
    return render(request, 'home/_device_live.html', {'bin': smart_bin})


@login_required(login_url='auth_view')
def device_controls_fragment(request, bin_id):
    smart_bin = _resolve_command_status(get_object_or_404(SmartBin, id=bin_id))
    return render(request, 'home/_device_controls.html', {'bin': smart_bin})


@login_required(login_url='auth_view')
def analytics_api(request):
    days = _period_days(request)
    trend, alerts, sample_count = _system_analytics(days)
    return JsonResponse({'trend': trend, 'alerts': alerts, 'sample_count': sample_count})


@login_required(login_url='auth_view')
def device_analytics_api(request, bin_id):
    smart_bin = get_object_or_404(SmartBin, id=bin_id)
    days = _period_days(request)
    data, sample_count, using_last_known, last_known_at = _device_history_payload(smart_bin, days)
    return JsonResponse({
        'device': smart_bin.device_id,
        'history': data,
        'sample_count': sample_count,
        'using_last_known': using_last_known,
        'last_known_at': timezone.localtime(last_known_at).isoformat() if last_known_at else None,
    })


@login_required(login_url='auth_view')
def system_report_csv(request):
    days = _period_days(request, default=30)
    since = timezone.now() - timedelta(days=days)
    response = HttpResponse(content_type='text/csv')
    stamp = timezone.localtime().strftime('%Y%m%d_%H%M')
    response['Content-Disposition'] = f'attachment; filename="SBWB_system_report_{stamp}.csv"'
    writer = csv.writer(response)
    writer.writerow(['SBWB Full System Report'])
    writer.writerow(['Generated', timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow(['Period (days)', days])
    writer.writerow([])
    writer.writerow(['Device ID', 'Location', 'Timestamp', 'Fill %', 'Gas ppm', 'Ambient °C', 'Element °C', 'Humidity %', 'Metal', 'UV', 'Heater', 'Lid', 'Bin Full', 'Interlock', 'Alert'])
    records = TelemetryRecord.objects.select_related('smart_bin').filter(recorded_at__gte=since).order_by('smart_bin__device_id', 'recorded_at')
    for r in records:
        writer.writerow([
            r.smart_bin.device_id, r.smart_bin.location_name,
            timezone.localtime(r.recorded_at).strftime('%Y-%m-%d %H:%M:%S'),
            r.fill_level, r.gas_value, r.temperature, r.element_temp, r.humidity,
            int(r.metal), int(r.uv), int(r.heater), int(r.lid), int(r.bin_full), int(r.interlock), r.alert_status,
        ])
    return response


@login_required(login_url='auth_view')
def device_report_csv(request, bin_id):
    smart_bin = get_object_or_404(SmartBin, id=bin_id)
    days = _period_days(request, default=30)
    since = timezone.now() - timedelta(days=days)
    response = HttpResponse(content_type='text/csv')
    stamp = timezone.localtime().strftime('%Y%m%d_%H%M')
    safe_id = ''.join(c for c in smart_bin.device_id if c.isalnum() or c in ('-', '_'))
    response['Content-Disposition'] = f'attachment; filename="SBWB_{safe_id}_report_{stamp}.csv"'
    writer = csv.writer(response)
    writer.writerow(['SBWB Device Report'])
    writer.writerow(['Device ID', smart_bin.device_id])
    writer.writerow(['Location', smart_bin.location_name])
    writer.writerow(['Generated', timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow(['Period (days)', days])
    writer.writerow([])
    writer.writerow(['Timestamp', 'Fill %', 'Gas ppm', 'Ambient °C', 'Element °C', 'Humidity %', 'Metal', 'UV', 'Heater', 'Lid', 'Bin Full', 'Interlock', 'Alert'])
    for r in smart_bin.telemetry_records.filter(recorded_at__gte=since).order_by('recorded_at'):
        writer.writerow([
            timezone.localtime(r.recorded_at).strftime('%Y-%m-%d %H:%M:%S'),
            r.fill_level, r.gas_value, r.temperature, r.element_temp, r.humidity,
            int(r.metal), int(r.uv), int(r.heater), int(r.lid), int(r.bin_full), int(r.interlock), r.alert_status,
        ])
    return response



def _pdf_response(filename):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _pdf_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='SBWBTitle', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=20, leading=24, textColor=colors.HexColor('#064E3B'), spaceAfter=6))
    styles.add(ParagraphStyle(name='SBWBSub', parent=styles['Normal'], fontSize=8.5, leading=12, textColor=colors.HexColor('#64748B')))
    styles.add(ParagraphStyle(name='SBWBHeading', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor('#0F172A'), spaceBefore=8, spaceAfter=6))
    styles.add(ParagraphStyle(name='SBWBBody', parent=styles['Normal'], fontSize=8.5, leading=12, textColor=colors.HexColor('#334155')))
    return styles


def _pdf_table(data, col_widths=None, header=True, font_size=7.5):
    table = Table(data, colWidths=col_widths, repeatRows=1 if header else 0, hAlign='LEFT')
    commands = [
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), font_size),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#334155')),
        ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]
    if header:
        commands += [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#064E3B')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')]
    table.setStyle(TableStyle(commands))
    return table


def _line_chart_series(category_names, series, labels, width=500, height=180):
    drawing = Drawing(width, height)
    if not category_names or not series:
        return drawing
    chart = HorizontalLineChart()
    chart.x = 45; chart.y = 28; chart.width = width - 70; chart.height = height - 52
    chart.data = series
    chart.categoryAxis.categoryNames = category_names
    chart.categoryAxis.labels.fontSize = 5.5
    chart.categoryAxis.labels.angle = 30
    chart.categoryAxis.labels.boxAnchor = 'ne'
    chart.categoryAxis.labels.dy = -3
    chart.valueAxis.labels.fontSize = 6
    chart.valueAxis.valueMin = 0
    chart.lines.strokeWidth = 1.5
    palette = [colors.HexColor('#059669'), colors.HexColor('#D97706'), colors.HexColor('#2563EB'), colors.HexColor('#DC2626')]
    for idx, _ in enumerate(series):
        chart.lines[idx].strokeColor = palette[idx % len(palette)]
    drawing.add(chart)
    # compact legend
    from reportlab.graphics.shapes import String, Rect
    x = 50
    for idx, label in enumerate(labels):
        drawing.add(Rect(x, height-13, 8, 2.5, fillColor=palette[idx % len(palette)], strokeColor=None))
        drawing.add(String(x+12, height-16, label, fontName='Helvetica', fontSize=6.5, fillColor=colors.HexColor('#334155')))
        x += 92
    return drawing


def _line_chart(records, fields, labels, width=500, height=180):
    category_names = [timezone.localtime(r.recorded_at).strftime('%d %b %H:%M') for r in records]
    series = [[float(getattr(r, field) or 0) for r in records] for field in fields]
    return _line_chart_series(category_names, series, labels, width=width, height=height)


def _pdf_unavailable():
    return HttpResponse('PDF reporting requires reportlab. Install dependencies from requirements.txt.', status=503, content_type='text/plain')


@login_required(login_url='auth_view')
def device_report_pdf(request, bin_id):
    if not REPORTLAB_AVAILABLE:
        return _pdf_unavailable()
    smart_bin = get_object_or_404(SmartBin, id=bin_id)
    days = _period_days(request, default=30)
    since = timezone.now() - timedelta(days=days)
    records = list(smart_bin.telemetry_records.filter(recorded_at__gte=since).order_by('recorded_at'))
    stamp = timezone.localtime().strftime('%Y%m%d_%H%M')
    safe_id = ''.join(c for c in smart_bin.device_id if c.isalnum() or c in ('-', '_'))
    response = _pdf_response(f'SBWB_{safe_id}_report_{stamp}.pdf')
    doc = SimpleDocTemplate(response, pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=15*mm, bottomMargin=15*mm, title=f'SBWB Device Report - {smart_bin.device_id}')
    st = _pdf_styles(); story = []
    story += [Paragraph('SBWB Device Report', st['SBWBTitle']), Paragraph(f'Generated {timezone.localtime():%Y-%m-%d %H:%M:%S} | Reporting period: {days} day(s)', st['SBWBSub']), Spacer(1, 8)]
    meta = [
        ['System', 'Value'], ['System name', smart_bin.system_name or '-'], ['System ID', smart_bin.device_id], ['System version', smart_bin.system_version or '-'],
        ['MAC address', smart_bin.mac_address or '-'], ['Location', smart_bin.location_name or '-'], ['Wi-Fi', smart_bin.wifi_ssid or '-'], ['IP address', smart_bin.ip_address or '-'],
        ['Connectivity', 'ONLINE' if smart_bin.is_online else 'OFFLINE'], ['Last seen', timezone.localtime(smart_bin.last_seen).strftime('%Y-%m-%d %H:%M:%S')], ['Alert status', smart_bin.alert_status],
    ]
    story += [_pdf_table(meta, [48*mm, 115*mm]), Spacer(1, 10)]
    summary = [['Current metric', 'Value'], ['Fill level', f'{smart_bin.fill_level}%'], ['Gas', f'{smart_bin.gas_value} ppm'], ['Ambient temperature', f'{smart_bin.temperature:.1f} C'], ['Element temperature', f'{smart_bin.elementTemp:.1f} C'], ['Humidity', f'{smart_bin.humidity:.1f}%'], ['UV', 'ON' if smart_bin.uvState else 'OFF'], ['Heater', 'ON' if smart_bin.heaterState else 'OFF'], ['Interlock', 'LOCKED' if smart_bin.interlock else 'UNLOCKED']]
    story += [Paragraph('Current operating snapshot', st['SBWBHeading']), _pdf_table(summary, [60*mm, 55*mm]), Spacer(1, 10)]
    if records:
        plotted = records[-48:]
        story += [Paragraph('Fill and gas trend', st['SBWBHeading']), _line_chart(plotted, ['fill_level','gas_value'], ['Fill %','Gas ppm']), Paragraph('Environmental trend', st['SBWBHeading']), _line_chart(plotted, ['temperature','element_temp','humidity'], ['Ambient C','Element C','Humidity %'])]
        details = [['Timestamp','Fill %','Gas','Ambient C','Element C','Humidity %','Alert']]
        for r in records[-60:]:
            details.append([timezone.localtime(r.recorded_at).strftime('%d %b %H:%M'), f'{r.fill_level:.1f}', f'{r.gas_value:.0f}', f'{r.temperature:.1f}', f'{r.element_temp:.1f}', f'{r.humidity:.1f}', r.alert_status])
        story += [PageBreak(), Paragraph('Recent telemetry samples', st['SBWBHeading']), _pdf_table(details, [29*mm,18*mm,18*mm,22*mm,22*mm,22*mm,30*mm], font_size=6.7)]
    else:
        story += [Paragraph('No historical samples are available in the selected period. The current live snapshot above is still valid.', st['SBWBBody'])]
    doc.build(story)
    return response


@login_required(login_url='auth_view')
def system_report_pdf(request):
    if not REPORTLAB_AVAILABLE:
        return _pdf_unavailable()
    days = _period_days(request, default=30)
    since = timezone.now() - timedelta(days=days)
    bins = list(SmartBin.objects.all().order_by('device_id'))
    records = list(TelemetryRecord.objects.select_related('smart_bin').filter(recorded_at__gte=since).order_by('recorded_at'))
    stamp = timezone.localtime().strftime('%Y%m%d_%H%M')
    response = _pdf_response(f'SBWB_full_system_report_{stamp}.pdf')
    doc = SimpleDocTemplate(response, pagesize=landscape(A4), rightMargin=12*mm, leftMargin=12*mm, topMargin=12*mm, bottomMargin=12*mm, title='SBWB Full System Report')
    st = _pdf_styles(); story=[]
    online = sum(1 for b in bins if b.is_online)
    story += [Paragraph('SBWB Full System Report', st['SBWBTitle']), Paragraph(f'Generated {timezone.localtime():%Y-%m-%d %H:%M:%S} | Reporting period: {days} day(s)', st['SBWBSub']), Spacer(1,8)]
    kpis = [['Registered devices','Online','Offline','Active alerts','Telemetry samples'], [str(len(bins)), str(online), str(len(bins)-online), str(sum(1 for b in bins if b.alert_status != 'NOMINAL')), str(len(records))]]
    story += [_pdf_table(kpis, [45*mm]*5), Spacer(1,10), Paragraph('Device fleet snapshot', st['SBWBHeading'])]
    fleet=[['System ID','Location','Status','Fill %','Gas ppm','UV','Heater','Interlock','Wi-Fi / IP','Version']]
    for b in bins:
        fleet.append([b.device_id,b.location_name,'ONLINE' if b.is_online else 'OFFLINE',str(b.fill_level),str(b.gas_value),'ON' if b.uvState else 'OFF','ON' if b.heaterState else 'OFF','LOCKED' if b.interlock else 'UNLOCKED',f'{b.wifi_ssid or "-"} / {b.ip_address or "-"}',b.system_version or '-'])
    story += [_pdf_table(fleet, [32*mm,38*mm,18*mm,16*mm,18*mm,14*mm,16*mm,20*mm,48*mm,22*mm], font_size=6.5)]
    trend, _, _ = _system_analytics(days)
    if trend:
        recent_trend = trend[-60:]
        story += [Spacer(1,10), Paragraph('System trend - fleet averages', st['SBWBHeading']), _line_chart_series(
            [point['label'] for point in recent_trend],
            [[float(point['fill']) for point in recent_trend], [float(point['gas']) for point in recent_trend]],
            ['Average fill %', 'Average gas ppm'], width=730, height=190)]
    story += [PageBreak(), Paragraph('Per-device reporting summary', st['SBWBHeading'])]
    for b in bins:
        qs = b.telemetry_records.filter(recorded_at__gte=since)
        agg = qs.aggregate(avg_fill=Avg('fill_level'), max_fill=Max('fill_level'), avg_gas=Avg('gas_value'), max_gas=Max('gas_value'), min_temp=Min('temperature'), max_temp=Max('temperature'))
        rows=[['Metric','Value'],['Samples',str(qs.count())],['Average fill',f"{agg['avg_fill']:.1f}%" if agg['avg_fill'] is not None else '-'],['Maximum fill',f"{agg['max_fill']:.1f}%" if agg['max_fill'] is not None else '-'],['Average gas',f"{agg['avg_gas']:.1f} ppm" if agg['avg_gas'] is not None else '-'],['Maximum gas',f"{agg['max_gas']:.1f} ppm" if agg['max_gas'] is not None else '-'],['Temperature range',f"{agg['min_temp']:.1f} - {agg['max_temp']:.1f} C" if agg['min_temp'] is not None else '-'],['Current alert',b.alert_status]]
        story += [KeepTogether([Paragraph(f'{b.device_id} - {b.location_name}', st['SBWBHeading']), _pdf_table(rows, [45*mm,55*mm]), Spacer(1,7)])]
    doc.build(story)
    return response


@csrf_exempt
def bin_telemetry_ingress(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        device_id = data.get('id')
        if not device_id:
            return JsonResponse({'error': 'Missing Device ID'}, status=400)

        alert = 'NOMINAL'
        if data.get('binFull', 0):
            alert = 'BIN_FULL'
        elif data.get('metal', 0):
            alert = 'METAL'

        smart_bin, _ = SmartBin.objects.update_or_create(
            device_id=device_id,
            defaults={
                'location_name': (data.get('location') or 'Unassigned')[:100],
                'system_name': (data.get('systemName') or 'Smart Biomedical Waste Bin')[:100],
                'system_version': (data.get('systemVersion') or '')[:40],
                'mac_address': (data.get('mac') or '')[:32],
                'wifi_ssid': (data.get('wifi') or '')[:64],
                'ip_address': (data.get('ip') or '')[:45],
                'fill_level': data.get('binLevel', 0),
                'gas_value': data.get('gas', 0),
                'alert_status': alert,
                'temperature': data.get('temperature', 0),
                'elementTemp': data.get('elementTemp', 0),
                'humidity': data.get('humidity', 0),
                'metal': data.get('metal', 0),
                'uv': data.get('uv', 0),
                'heater': data.get('heaterState', 0),
                'lid': data.get('lid', 0),
                'binFull': data.get('binFull', 0),
                'interlock': data.get('interlock', 0),
                'binLevel': data.get('binLevel', 0),
                'heaterState': data.get('heaterState', 0),
                'uvState': data.get('uvState', 0),
            },
        )

        # Keep live state at heartbeat frequency, but rate-limit historical samples.
        # Alerts bypass the interval so important state changes are always preserved.
        latest_record = smart_bin.telemetry_records.first()
        should_archive = (
            latest_record is None
            or (timezone.now() - latest_record.recorded_at).total_seconds() >= HISTORY_SAMPLE_SECONDS
            or latest_record.alert_status != alert
        )
        if should_archive:
            TelemetryRecord.objects.create(
                smart_bin=smart_bin,
                fill_level=data.get('binLevel', 0),
                gas_value=data.get('gas', 0),
                temperature=data.get('temperature', 0),
                element_temp=data.get('elementTemp', 0),
                humidity=data.get('humidity', 0),
                metal=bool(data.get('metal', 0)),
                uv=bool(data.get('uv', 0)),
                heater=bool(data.get('heaterState', 0)),
                lid=bool(data.get('lid', 0)),
                bin_full=bool(data.get('binFull', 0)),
                interlock=bool(data.get('interlock', 0)),
                alert_status=alert,
            )

        ack = data.get('ack', 'NONE')
        if ack and ack != 'NONE' and smart_bin.last_command == ack and smart_bin.last_command_status == 'PENDING':
            smart_bin.last_command_status = 'ACKED'
            smart_bin.last_command_time = timezone.now()
            smart_bin.save(update_fields=['last_command_status', 'last_command_time'])

        cmd_to_send = smart_bin.pending_command or 'NONE'
        if smart_bin.pending_command:
            smart_bin.pending_command = None
            smart_bin.save(update_fields=['pending_command'])

        return JsonResponse({'status': 'OK', 'command': cmd_to_send}, status=200)

    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({'error': 'Malformed JSON'}, status=400)


@csrf_exempt
def device_command(request, bin_id, command):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    smart_bin = get_object_or_404(SmartBin, id=bin_id)
    smart_bin.pending_command = command
    smart_bin.last_command = command
    smart_bin.last_command_status = 'PENDING'
    smart_bin.last_command_time = timezone.now()
    smart_bin.save()

    if request.headers.get('HX-Request'):
        return render(request, 'home/_command_banner.html', {'bin': smart_bin})
    return JsonResponse({'status': 'queued', 'command': command}, status=200)
