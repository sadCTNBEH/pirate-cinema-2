import threading
from unittest.mock import Mock

from backend.infrastructure.window_geometry import (
    Display,
    WindowGeometry,
    WindowGeometryManager,
    calculate_fullscreen_bounds,
    calculate_initial_bounds,
    calculate_pip_bounds,
    calculate_restore_bounds,
    find_display,
    find_display_for_bounds,
    placement,
)


def saved(display, bounds, **kwargs):
    store = WindowGeometry({}, lambda data: None, delay=60)
    store.remember(bounds, display, **kwargs)
    store.flush()
    return store.state['pip' if kwargs.get('pip') else 'normal']


def test_restore_secondary_monitor_and_normal_bounds_of_maximized_window():
    main = Display('main', 0, 0, 1920, 1040)
    second = Display('second', -1600, 80, 1600, 900)
    record = saved(second, [-1500, 120, 1000, 700], maximized=True)
    result = placement(record, [main, second])
    assert result['bounds'] == [-1500, 120, 1000, 700]
    assert result['maximized'] is True


def test_disconnected_monitor_and_resolution_change_keep_entire_window_visible():
    old = Display('second', 1920, 0, 2560, 1400)
    record = saved(old, [3300, 900, 1300, 900])
    small = Display('main', 0, 0, 1280, 720)
    result = placement(record, [small])
    assert result['monitor'] == 'main'
    x, y, width, height = result['bounds']
    assert 0 <= x <= 1280-width and 0 <= y <= 720-height
    resized = placement(record, [Display('second', -1280, 0, 1280, 720)])
    x, y, width, height = resized['bounds']
    assert -1280 <= x <= -width and 0 <= y <= 720-height


def test_dpi_change_scales_saved_size_and_monitor_relative_position():
    old = Display('screen', 0, 0, 1920, 1080, 96)
    record = saved(old, [100, 80, 800, 500])
    result = placement(record, [Display('screen', 1920, 0, 2560, 1440, 144)])
    assert result['bounds'] == [2070, 120, 1200, 750]


def test_invalid_geometry_falls_back_to_valid_work_area():
    display = Display('main', 0, 0, 1366, 728)
    for bad in (None, [], {'bounds': [float('nan'), None, 0, -1]}, {'bounds': [999999, 1, 'bad', True]}):
        x, y, width, height = placement(bad, [display])['bounds']
        assert 640 <= width <= 1366 and 420 <= height <= 728
        assert 0 <= x <= 1366-width and 0 <= y <= 728-height
    assert placement({}, []) is None


def test_pip_fullscreen_and_minimized_do_not_replace_main_geometry():
    screen = Display('screen', 0, 0, 1920, 1040)
    written = []
    store = WindowGeometry({}, written.append, delay=60)
    store.remember([20, 30, 1100, 700], screen)
    normal = store.state['normal'].copy()
    store.remember([1450, 700, 420, 268], screen, pip=True)
    store.remember([0, 0, 1920, 1080], screen, fullscreen=True)
    store.remember([-32000, -32000, 1, 1], screen, minimized=True)
    store.flush()
    restored = WindowGeometry(written[-1], lambda data: None)
    assert restored.state['normal'] == normal
    assert restored.restore([screen], pip=True)['bounds'] == [1450, 700, 420, 268]
    assert restored.restore([screen])['bounds'] == [20, 30, 1100, 700]


def test_geometry_events_are_debounced_and_flush_preserves_last_position():
    screen = Display('screen', 0, 0, 1920, 1040)
    written, done = [], threading.Event()
    store = WindowGeometry({}, lambda data: (written.append(data), done.set()), delay=0.03)
    for x in range(20):
        store.remember([x, 30, 1100, 700], screen)
    assert done.wait(1)
    assert len(written) == 1
    assert written[0]['window_geometry']['normal']['bounds'][0] == 19


def test_find_display_and_display_for_bounds():
    main = Display("main", 0, 0, 1920, 1080)
    second = Display("second", 1920, 0, 2560, 1440)
    displays = [main, second]

    assert find_display(displays, name="second") == second
    assert find_display(displays, point=(2000, 100)) == second
    assert find_display(displays, point=(100, 100)) == main
    assert find_display(displays, point=(9999, 9999)) == main
    assert find_display([], name="main") is None

    assert find_display_for_bounds(displays, [2000, 50, 800, 600]) == second
    assert find_display_for_bounds(displays, [100, 50, 800, 600]) == main


def test_calculate_fullscreen_bounds():
    screen_rect = (1920, 0, 2560, 1440)
    bounds, viewport = calculate_fullscreen_bounds(screen_rect, client_size=(1920, 1080))
    assert bounds == (1920, 0, 2560, 1440)
    assert viewport == (2560, 1440)

    bounds_dict, viewport_dict = calculate_fullscreen_bounds(
        {"x": 0, "y": 0, "width": 1920, "height": 1080},
        client_size={"width": 2000, "height": 1200},
    )
    assert bounds_dict == (0, 0, 1920, 1080)
    assert viewport_dict == (2000, 1200)


def test_calculate_restore_bounds():
    wa_second = Display("second", 1920, 0, 2560, 1400)
    # Valid saved bounds on secondary screen
    saved_bounds = [2000, 100, 1200, 800]
    rx, ry, rw, rh = calculate_restore_bounds(wa_second, saved_bounds)
    assert (rx, ry, rw, rh) == (2000, 100, 1200, 800)

    # Fallback to centering on work area
    rx, ry, rw, rh = calculate_restore_bounds(wa_second, None, default_size=(1280, 800))
    assert rw == 1280
    assert rh == 800
    assert rx == 1920 + (2560 - 1280) // 2
    assert ry == 0 + (1400 - 800) // 2


def test_calculate_pip_bounds():
    wa_second = Display("second", 1920, 0, 1920, 1080)
    # Default pip bottom-right placement
    px, py, pw, th, vh = calculate_pip_bounds(wa_second, header_height=32, margin=24)
    assert pw == 420
    assert th == 268
    assert vh == 268 - 32
    assert px == 1920 + 1920 - 420 - 24
    assert py == 0 + 1080 - 268 - 24

    # Restoring saved pip bounds
    saved_pip = [2100, 500, 500, 320]
    px, py, pw, th, vh = calculate_pip_bounds(wa_second, saved_pip_bounds=saved_pip, header_height=32)
    assert (px, py, pw, th) == (2100, 500, 500, 320)
    assert vh == 320 - 32

    # Oversized or full-screen bounds are rejected and fallback to bottom-right
    corrupt_pip = [284, 49, 1536, 960]
    px, py, pw, th, vh = calculate_pip_bounds(wa_second, saved_pip_bounds=corrupt_pip, header_height=32, margin=24)
    assert pw == 420
    assert th == 268
    assert px == 1920 + 1920 - 420 - 24
    assert py == 0 + 1080 - 268 - 24


def test_calculate_initial_bounds_with_and_without_settings():
    main = Display("main", 0, 0, 1920, 1080)
    second = Display("second", 1920, 0, 2560, 1440)
    displays = [main, second]

    # 1. Fresh start: centered on primary display
    x, y, w, h, maximized = calculate_initial_bounds({}, displays=displays, default_size=(1280, 800))
    assert w == 1280
    assert h == 800
    assert x == (1920 - 1280) // 2
    assert y == (1080 - 800) // 2
    assert maximized is False

    # 2. Saved on secondary display: returns secondary display coordinates directly
    settings = {
        "window_geometry": {
            "normal": {
                "bounds": [2100, 150, 1400, 900],
                "monitor": "second",
                "dpi": 96,
                "work_area": {"name": "second", "x": 1920, "y": 0, "width": 2560, "height": 1440, "dpi": 96},
                "maximized": True,
            }
        }
    }
    x, y, w, h, maximized = calculate_initial_bounds(settings, displays=displays)
    assert x == 2100
    assert y == 150
    assert w == 1400
    assert h == 900
    assert maximized is True


def test_window_geometry_manager():
    main = Display("main", 0, 0, 1920, 1080)
    saved_data = []
    geom = WindowGeometry({}, saved_data.append, delay=0.01)
    manager = WindowGeometryManager(geom)

    # Mock pywebview window
    win = Mock(x=200, y=100, width=1280, height=800, native=None)
    assert manager.capture(win, displays=[main]) is True
    geom.flush()
    assert len(saved_data) == 1
    assert saved_data[0]["window_geometry"]["normal"]["bounds"] == [200, 100, 1280, 800]

    # Apply restored geometry
    restored = manager.apply_to_window(win, displays=[main])
    assert restored["bounds"] == [200, 100, 1280, 800]
    assert win.resize.called
    assert win.move.called

