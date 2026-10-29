import threading

from backend.infrastructure.window_geometry import Display, WindowGeometry, placement


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

