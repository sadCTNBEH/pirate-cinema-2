"""Exercise the real Lua UI handlers without opening a video window."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_cinema_ui_reacts_without_waiting_for_progress_timer(tmp_path):
    root = Path(__file__).resolve().parents[1]
    bundled = root / 'mpv' / 'mpv.com'
    binary = str(bundled) if bundled.is_file() else shutil.which('mpv')
    if not binary:
        pytest.skip('MPV is required for the Lua interaction test')
    prefix = r'''
local test_mp = require 'mp'
local handlers, observers = {}, {}
local preview_messages, timeout_callbacks = {}, {}
local real_script_message=test_mp.register_script_message
test_mp.register_script_message=function(name,fn) preview_messages[name]=fn; return real_script_message(name,fn) end
local real_timeout=test_mp.add_timeout
test_mp.add_timeout=function(seconds,fn) timeout_callbacks[#timeout_callbacks+1]=fn; return real_timeout(seconds,fn) end
local idle_callback
local overlay_count=0
local create_overlay=test_mp.create_osd_overlay
test_mp.create_osd_overlay=function(...) overlay_count=overlay_count+1; return create_overlay(...) end
test_mp.add_forced_key_binding=function(_,name,fn) handlers[name]=fn end
test_mp.observe_property=function(name,_,fn) observers[name]=fn end
test_mp.register_idle=function(fn) idle_callback=fn end
'''
    checks = r'''
local ok,err=xpcall(function()
    local now, x, y, updates = 0, 871, 511, 0
    local fullscreen = false
    windows_native_cursor=false
    local commands={}
    mp.get_time=function() return now end
    mp.get_osd_size=function() return 960,540,1 end
    mp.get_mouse_pos=function() return x,y end
    mp.get_property_native=function(name,fallback)
        if name=='fullscreen' then return fullscreen end
        if name=='duration' then return 120 end
        if name=='time-pos' then return 10 end
        return fallback
    end
    mp.commandv=function(...) commands[#commands+1]={...} end
    overlay.update=function() updates=updates+1 end
    overlay.remove=function() end

    -- The first click on hidden controls opens its menu, rather than being eaten.
    visible=false; dirty=false
    handlers['cinema-click']({event='down'})
    assert(menu=='more','first click must open the menu')
    idle_callback()
    assert(overlay.data:find('Настройки',1,true),'menu must render in this event batch')

    -- Closing a menu redraws in the same batch, without advancing any timer.
    x,y=918,334
    handlers['cinema-click']({event='down'})
    idle_callback()
    assert(menu==nil,'menu close must respond immediately')
    assert(not overlay.data:find('Настройки',1,true),'closed menu must disappear immediately')

    -- Moving inside the same button should not continuously redraw the OSD.
    x,y=44,511
    handlers['cinema-move'](); idle_callback()
    local before=updates
    for _=1,100 do handlers['cinema-move'](); idle_callback() end
    assert(updates==before,'stationary hover must not redraw')

    -- A hidden or fading playback button executes on the first click, exactly once.
    visible=false; dirty=false
    handlers['cinema-click']({event='down'})
    assert(#commands==1 and commands[1][3]=='["cycle","pause"]','hidden button must execute once')
    fade_started=0; now=0.05
    handlers['cinema-click']({event='down'})
    assert(#commands==2 and fade_started==nil,'fading button must execute immediately')

    dirty=false; progress_timer:kill()
    observers['time-pos']()
    assert(not dirty and progress_timer:is_enabled(),'only progress may wait for its timer')
    progress_timer:kill(); visible=false
    observers['time-pos']()
    assert(not progress_timer:is_enabled(),'hidden progress must not schedule redraws')

    visible=true; menu=nil; drag=nil; now=1; begin_hide()
    assert(fade_timer:is_enabled(),'fade timer must run only during fade')
    now=1.13; render()
    assert(not visible and not fade_timer:is_enabled(),'fade timer must stop after hiding')

    -- Fullscreen double click must preserve the pause state before the first click.
    commands={}; menu=nil; x,y=450,250; now=2
    visible=true; dirty=true; activity(); render()
    handlers['cinema-click']({event='down'})
    now=2.1
    handlers['cinema-click']({event='down'})
    assert(#commands==3,'double click must undo its first pause toggle and toggle fullscreen once')
    assert(commands[2][3]=='["set_property","pause",false]','double click must preserve playback')
    assert(commands[3][3]=='["cinema","fullscreen"]','double click must toggle fullscreen')
    now=2.5; commands={}; visible=false
    handlers['cinema-click']({event='down'})
    now=2.6
    handlers['cinema-click']({event='down'})
    assert(#commands==1 and commands[1][3]=='["cinema","fullscreen"]','hidden UI double click must toggle fullscreen once')

    -- The cursor stays visible during panel/menu interaction and returns on fullscreen resize.
    activity()
    assert(cursor_mode=='no','activity must reveal cursor')
    menu='more'; begin_hide()
    assert(cursor_mode=='no','open menu must retain cursor')
    menu=nil; now=3; begin_hide(); now=3.13; render()
    assert(cursor_mode=='always','cursor must hide only with the panel')
    observers['fullscreen']()
    assert(visible and cursor_mode=='no','fullscreen transition must restore cursor')

    -- Windows uses one native cursor, with no OSD pointer or video-rate redraws.
    assert(overlay_count==1,'the UI must not create a video-composited cursor overlay')
    windows_native_cursor=true; fullscreen=true
    observers['fullscreen'](); idle_callback()
    assert(cursor_mode=='no','Windows fullscreen must keep the native cursor visible')
    x,y=500,250; handlers['cinema-move'](); idle_callback()
    local previous_updates=updates
    for i=1,100 do x=500+i/10; handlers['cinema-move'](); idle_callback() end
    assert(updates==previous_updates,'native cursor movement must not redraw video OSD')
    menu=nil; now=4; begin_hide(); now=4.13; render()
    assert(cursor_mode=='no','hiding controls must not hide the Windows native cursor')
    fullscreen=false; observers['fullscreen'](); idle_callback()
    assert(cursor_mode=='no','windowed mode must retain the same native cursor')

    -- Preview uses the same bounded timeline geometry and never seeks the video.
    menu=nil; visible=true; fade_started=nil; drag=nil; commands={}
    x,y=24,476; render()
    assert(preview_position(0)==0 and preview_position(24)==0,'start must clamp to zero')
    assert(preview_position(936)<120 and preview_position(1000)>119,'end must remain inside duration')
    assert(clock(0)=='00:00' and clock(65)=='01:05' and clock(3661)=='1:01:01','timecode format')
    x=480; handlers['cinema-move'](); idle_callback()
    assert(preview.time==60 and preview.bucket==60,'cursor midpoint must map to midpoint time')
    assert(preview_timer:is_enabled(),'generation must be debounced')
    timeout_callbacks[1]()
    assert(commands[#commands][2]=='cinema-preview','preview must use a separate request, not a seek')
    local token=tostring(preview.serial)
    preview_messages['cinema-preview-result'](token,'test.bgra'); idle_callback()
    assert(preview.shown and overlay.data:find('01:00',1,true),'frame and timecode must appear together')
    local n=#commands
    for i=1,20 do handlers['cinema-move'](); idle_callback() end
    assert(#commands==n,'same bucket must not request or upload its frame repeatedly')
    x=936; handlers['cinema-move'](); idle_callback()
    assert(not preview.shown,'an unavailable frame must hide the thumbnail')
    assert(not overlay.data:find(clock(preview.time),1,true),'missing frame must hide the hover timecode too')
    assert(not overlay.data:find('Нет кадра',1,true),'missing frame must not show a placeholder')
    y=250; handlers['cinema-move'](); idle_callback()
    assert(not preview.time and not preview.shown,'leaving timeline must remove the frame')
    preview_messages['cinema-preview-result'](token,'old-film.bgra')
    assert(not preview.path,'stale responses must be ignored')
    x,y=480,476; handlers['cinema-move'](); idle_callback()
    preview_messages['cinema-preview-reset']()
    assert(not preview.path and not preview.time,'new film must clear the thumbnail')

    preview_messages['cinema-preview-mode']('stream')
    x,y=480,476; handlers['cinema-move'](); idle_callback()
    x=510; handlers['cinema-move'](); idle_callback()
    assert(preview.bucket==60,'buffer previews must share one frame per ten seconds')
    timeout_callbacks[1]()
    preview_messages['cinema-preview-result'](tostring(preview.serial),'')
    preview_timer:kill()
    observers['demuxer-cache-state']('demuxer-cache-state',{['seekable-ranges']={{start=0,['end']=30}}})
    assert(not preview_timer:is_enabled(),'unbuffered target must not poll the decoder')
    observers['demuxer-cache-state']('demuxer-cache-state',{['seekable-ranges']={{start=0,['end']=100}}})
    assert(preview_timer:is_enabled(),'newly buffered target must retry without moving the pointer')

    -- Scrubbing chooses a position locally; torrent playback is not live-seeked.
    clear_preview(); commands={}; x,y=200,476
    handlers['cinema-click']({event='down'})
    for i=1,150 do x=200+i*3; handlers['cinema-move'](); idle_callback() end
    assert(seek_target and seek_target>80,'drag must update its selected position immediately')
    assert(overlay.data:find(clock(seek_target),1,true),'selected time must be rendered')
    assert(#commands==0,'dragging must not flood MPV with seek commands')
    local target=seek_target
    handlers['cinema-click']({event='up'})
    assert(#commands==1 and commands[1][3]:find('cinema%-seek'),'release must commit one final seek')
    assert(seek_pending==target,'thumb must keep the selected position until confirmed')
    handlers['cinema-click']({event='up'})
    assert(#commands==1,'duplicate release must not seek twice')
    observers['time-pos']()
    assert(seek_pending==target,'old progress must not overwrite the pending target')
    local actual_property=mp.get_property_native
    mp.get_property_native=function(name,fallback)
        if name=='time-pos' then return target end
        return actual_property(name,fallback)
    end
    observers['time-pos']()
    assert(not seek_pending,'confirmed MPV position must release the pending thumb')
    mp.get_property_native=actual_property
    x,y=400,476; handlers['cinema-click']({event='down'})
    handlers['cinema-leave']()
    assert(not seek_target and not drag and #commands==1,'leaving window must cancel the uncommitted drag')
end,debug.traceback)
-- Restore the native command function intercepted above before leaving MPV.
if ok then print('Cinema interaction checks passed') else print(err) end
test_quit(ok)
'''
    # Keep quit available even while the test captures UI commands.
    prefix += "local test_command=test_mp.commandv\nlocal function test_quit(ok) test_command('quit',ok and 0 or 1) end\n"
    script = tmp_path / 'cinema_interaction.lua'
    script.write_text(prefix + (root / 'backend/infrastructure/mpv/cinema.lua').read_text(encoding='utf-8') + checks, encoding='utf-8')
    result = subprocess.run([binary, '--no-config', '--vo=null', '--ao=null', '--idle=yes', f'--script={script}'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Cinema interaction checks passed' in result.stdout, result.stdout + result.stderr
