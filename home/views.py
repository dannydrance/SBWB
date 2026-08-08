import json
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from .models import SmartBin

GAS_ANOMALY_THRESHOLD = 600  # ppm — kept in one place so table, cards, and map all agree

def auth_view(request):
    """Renders the combined authentication screen."""
    if request.user.is_authenticated:
        return redirect('dashboard_home')
    return render(request, 'home/auth.html')

def login_action(request):
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        user = authenticate(request, username=u, password=p)
        if user is not None:
            login(request, user)
            return redirect('dashboard_home')
    return redirect('auth_view')

def register_action(request):
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        if not User.objects.filter(username=u).exists():
            User.objects.create_user(username=u, password=p)
            user = authenticate(request, username=u, password=p)
            login(request, user)
            return redirect('dashboard_home')
    return redirect('auth_view')

def logout_action(request):
    logout(request)
    return redirect('auth_view')

def _dashboard_context():
    """Shared by the full dashboard page and its HTMX live-polling fragment."""
    bins = SmartBin.objects.all()
    online_count = sum(1 for b in bins if b.is_online)
    return {
        'bins': bins,
        'total': bins.count(),
        'online': online_count,
        'offline': bins.count() - online_count,
        'bins_full_count': sum(1 for b in bins if b.binFull),
        'gas_anomalies': sum(1 for b in bins if b.gas_value > GAS_ANOMALY_THRESHOLD),
        'critical_bins': [b for b in bins if b.alert_status != 'NOMINAL'],
    }

@login_required(login_url='auth_view')
def dashboard_home(request):
    return render(request, 'home/dashboard.html', _dashboard_context())

@login_required(login_url='auth_view')
def dashboard_stats_fragment(request):
    """HTMX polling target — re-renders just the 4 top stat cards."""
    return render(request, 'home/_dashboard_stats.html', _dashboard_context())

@login_required(login_url='auth_view')
def dashboard_table_fragment(request):
    """HTMX polling target — re-renders the bins table + alarms log (map is untouched)."""
    return render(request, 'home/_dashboard_table.html', _dashboard_context())

@login_required(login_url='auth_view')
def system_status(request):
    bins = SmartBin.objects.all()
    critical_count = bins.exclude(alert_status='NOMINAL').count()
    return render(request, 'home/status.html', {
        'total': bins.count(),
        'online': sum(1 for b in bins if b.is_online),
        'offline': bins.count() - sum(1 for b in bins if b.is_online),
        'critical_count': critical_count
    })

@login_required(login_url='auth_view')
def device_detail(request, bin_id):
    smart_bin = get_object_or_404(SmartBin, id=bin_id)
    bins = SmartBin.objects.all()

    context = {
        'bin': smart_bin,
        'status': bins,
    }

    return render(request, 'home/device_detail.html', context)

@login_required(login_url='auth_view')
def device_live_fragment(request, bin_id):
    """HTMX polling target — re-renders the KPI cards, status flags, sensor table
    and command confirmation banner for one device without touching the map."""
    smart_bin = get_object_or_404(SmartBin, id=bin_id)
    return render(request, 'home/_device_live.html', {'bin': smart_bin})

@csrf_exempt
def bin_telemetry_ingress(request):
    if request.method == 'POST':
        print(request.body)
        try:
            data = json.loads(request.body)
            device_id = data.get('id')

            if not device_id:
                return JsonResponse({'error': 'Missing Device ID'}, status=400)

            # NOTE: the ESP32 payload uses "binFull" / "metal" (see NetworkModule.cpp's
            # buildTelemetry) — matching those keys here, not "bin_full"/"metal_detected",
            # which never matched anything the device actually sends.
            alert = 'NOMINAL'
            if data.get('binFull', 0):
                alert = 'BIN_FULL'
            elif data.get('metal', 0):
                alert = 'METAL'

            # Unpack tuple (object, created) from update_or_create
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
                    'heaterState': data.get('heaterState'),
                    'uvState': data.get('uvState'),
                }
            )

            # If this post is confirming the command we last queued for it, flip the
            # status to ACKED so the dashboard can show a success message.
            ack = data.get('ack', 'NONE')
            if (ack and ack != 'NONE'
                    and smart_bin.last_command == ack
                    and smart_bin.last_command_status == 'PENDING'):
                smart_bin.last_command_status = 'ACKED'
                smart_bin.last_command_time = timezone.now()
                smart_bin.save()

            # Retrieve queued command for ESP32 and clear queue
            cmd_to_send = smart_bin.pending_command or "NONE"
            if smart_bin.pending_command:
                smart_bin.pending_command = None
                smart_bin.save()

            # Respond with JSON containing the command payload
            return JsonResponse({
                'status': 'OK',
                'command': cmd_to_send
            }, status=200)

        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Malformed JSON'}, status=400)

    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def device_command(request, bin_id, command):
    if request.method == 'POST':
        smart_bin = get_object_or_404(SmartBin, id=bin_id)

        # Queue command for ESP32's next telemetry poll, and record it so we can
        # confirm (ack) it once the device reports back that it applied.
        smart_bin.pending_command = command
        smart_bin.last_command = command
        smart_bin.last_command_status = 'PENDING'
        smart_bin.last_command_time = timezone.now()
        smart_bin.save()

        # HTMX buttons target #command-banner directly for instant feedback;
        # a plain JSON caller (e.g. a script) still gets a normal API response.
        if request.headers.get('HX-Request'):
            return render(request, 'home/_command_banner.html', {'bin': smart_bin})

        return JsonResponse({'status': 'queued', 'command': command}, status=200)
    return JsonResponse({'error': 'Method not allowed'}, status=405)