import csv
import json
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import SmartBin, TelemetryRecord

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


@login_required(login_url='auth_view')
def device_detail(request, bin_id):
    smart_bin = _resolve_command_status(get_object_or_404(SmartBin, id=bin_id))
    days = _period_days(request)
    since = timezone.now() - timedelta(days=days)
    records = list(smart_bin.telemetry_records.filter(recorded_at__gte=since).order_by('recorded_at')[:500])
    history = [{
        'label': timezone.localtime(r.recorded_at).strftime('%d %b %H:%M'),
        'fill': r.fill_level,
        'gas': r.gas_value,
        'temperature': r.temperature,
        'humidity': r.humidity,
        'elementTemp': r.element_temp,
    } for r in records]

    context = {
        'bin': smart_bin,
        'days': days,
        'history_json': json.dumps(history),
        'sample_count': len(records),
        'telemetry_endpoint': request.build_absolute_uri('/api/telemetry/'),
    }
    return render(request, 'home/device_detail.html', context)


@login_required(login_url='auth_view')
def device_live_fragment(request, bin_id):
    smart_bin = _resolve_command_status(get_object_or_404(SmartBin, id=bin_id))
    return render(request, 'home/_device_live.html', {'bin': smart_bin})


@login_required(login_url='auth_view')
def analytics_api(request):
    days = _period_days(request)
    trend, alerts, sample_count = _system_analytics(days)
    return JsonResponse({'trend': trend, 'alerts': alerts, 'sample_count': sample_count})


@login_required(login_url='auth_view')
def device_analytics_api(request, bin_id):
    smart_bin = get_object_or_404(SmartBin, id=bin_id)
    days = _period_days(request)
    since = timezone.now() - timedelta(days=days)
    records = smart_bin.telemetry_records.filter(recorded_at__gte=since).order_by('recorded_at')[:500]
    data = [{
        'label': timezone.localtime(r.recorded_at).strftime('%d %b %H:%M'),
        'fill': r.fill_level,
        'gas': r.gas_value,
        'temperature': r.temperature,
        'humidity': r.humidity,
        'elementTemp': r.element_temp,
    } for r in records]
    return JsonResponse({'device': smart_bin.device_id, 'history': data, 'sample_count': len(data)})


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
                'location_name': data.get('location', 'Unassigned'),
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
