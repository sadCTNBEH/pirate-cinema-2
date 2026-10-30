"""Run the shipped Lua OSD and real MPV Lua runtime, including its click handlers."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_segments_in_real_mpv(tmp_path):
    root = Path(__file__).resolve().parents[1]
    bundled = root / 'mpv/mpv.com'
    binary = str(bundled) if bundled.is_file() else shutil.which('mpv')
    if not binary:
        pytest.skip('MPV unavailable')
    prefix = r'''
local runtime=require 'mp'
local quit=runtime.commandv
local handlers, events, messages, periodic={},{},{},{}
runtime.add_forced_key_binding=function(_,name,fn) handlers[name]=fn end
runtime.register_event=function(name,fn) events[name]=events[name] or {}; table.insert(events[name],fn) end
runtime.register_script_message=function(name,fn) messages[name]=fn end
local real_periodic=runtime.add_periodic_timer
runtime.add_periodic_timer=function(interval,fn) periodic[#periodic+1]=fn; return real_periodic(interval,fn) end
'''
    checks = r'''
local ok,err=xpcall(function()
    local position,duration,now,x,y=12,300,0,500,250
    local raw={{time=0,title='Recap'},{time=10,title='Opening'},{time=40,title='Story'},
        {time=200,title='Credits'},{time=240,title='Post credit scene'},{time=260,title='Preview'},{time=280,title='End'}}
    local commands={}
    local paused=false
    mp.get_time=function() return now end
    mp.get_mouse_pos=function() return x,y end
    mp.get_osd_size=function() return 960,540,1 end
    mp.get_property=function(name) if name=='path' then return 'episode-2' end end
    mp.get_property_number=function(name,fallback)
        if name=='time-pos' then return position elseif name=='duration' then return duration end
        return fallback
    end
    mp.get_property_native=function(name,fallback)
        if name=='chapter-list' then return raw elseif name=='duration' then return duration
        elseif name=='time-pos' then return position elseif name=='pause' then return paused end
        return fallback
    end
    mp.commandv=function(...)
        local cmd={...}
        if cmd[2]=='cinema-action' and cmd[3]:find('cinema-menu',1,true) then return end
        commands[#commands+1]=cmd
    end
    overlay.update=function() end
    overlay.remove=function() end
    local tick=periodic[#periodic]
    tick(); render()
    assert(overlay.data:find('Пропустить заставку',1,true),'native OSD must contain skip button')
    assert(active_segment.source=='chapter' and not countdown,'chapter titles alone never start auto-skip')
    toggle_menu('chapters'); render()
    assert(overlay.data:find('00:10',1,true) and overlay.data:find('Opening',1,true),'chapters menu timestamps')
    local clicked=false
    for _,r in ipairs(regions) do
        if r.w==388 and r.y>0 then r.fn(); clicked=true; break end
    end
    assert(clicked and commands[#commands][3]:find('cinema%-seek'),'chapter menu must route seek through service')
    menu=nil; commands={}
    x,y=800,395; render(); handlers['cinema-click']({event='down'}); handlers['cinema-click']({event='up'})
    assert(#commands==1 and commands[1][3]=='["cinema-seek",40]','native skip click seeks exactly once')
    tick(); render(); assert(not overlay.data:find('Пропустить заставку',1,true),'skip disappears immediately')
    position=100; tick(); assert(not active_segment,'ordinary chapter cannot be skipped')
    raw={}; tick(); menu='more'; render()
    assert(not overlay.data:find('Главы',1,true),'no empty chapters menu')
    raw={{time=0,title='Opening scene'},{time=50,title='Story'}}
    position=10; tick(); assert(not active_segment,'ambiguous title cannot be skipped')
    raw={{time=0,title='Opening'}}; tick(); assert(not active_segment,'missing boundary cannot be skipped')
    raw={{time=0,title='Opening'},{time=0,title='Story'}}; tick(); assert(not active_segment,'duplicate timestamps invalid')
    raw={{time=10,title='Opening'},{time=40,title='Story'}}; skipped={}
    messages['cinema-segments'](utils.format_json({path='old-file',auto=true,segments={{kind='intro',start=10,['end']=40,source='introdb'}}}))
    assert(#segment_data==0,'stale file response rejected')
    messages['cinema-segments'](utils.format_json({path='episode-2',auto=true,segments={{kind='intro',start=10,['end']=40,source='introdb'}}}))
    position=12; menu=nil; commands={}; tick(); assert(countdown,'corroborated IntroDB starts countdown')
    now=2; paused=true; tick(); assert(countdown.elapsed==0,'paused playback does not consume countdown')
    paused=false; x,y=800,355; render(); handlers['cinema-click']({event='down'})
    assert(not countdown and cancelled[active_segment.key],'cancel button cancels countdown')
    for i=1,100 do now=now+.1; tick() end
    assert(#commands==0,'cancelled countdown never seeks')
    cancelled={}; commands={}; tick()
    for i=1,82 do now=now+.1; tick() end
    assert(#commands==1 and commands[1][3]=='["cinema-seek",40]','auto-skip fires exactly once after eight seconds')
    skipped={}; cancelled={}; segment_data={{kind='intro',start=10,['end']=400,source='introdb'}}
    tick(); assert(active_segment.source=='chapter' and not countdown,'out-of-duration data cannot auto-skip')
    segment_data={{kind='intro',start=15,['end']=45,source='introdb'}}; position=20
    tick(); assert(active_segment.source=='introdb' and not countdown,'different release boundaries forbid auto-skip')
    segment_data={}; raw={{time=200,title='Credits'},{time=240,title='Post credit scene'}}
    position=210; has_next=true; tick(); render()
    assert(overlay.data:find('Следующая серия',1,true),'credits expose existing next action')
    skip_segment(); assert(commands[#commands][3]=='["cinema-seek",240]','credits must preserve the additional scene')
    position=245; tick(); assert(not active_segment,'post-credit scene is not skipped')
    for _,fn in ipairs(events['start-file']) do fn() end
    assert(#segment_data==0 and not active_segment and not countdown and not has_next,'file switch clears previous intervals')
end,debug.traceback)
if ok then print('Segment OSD checks passed') else print(err) end
quit('quit',ok and 0 or 1)
'''
    script = tmp_path / 'segments_test.lua'
    script.write_text(prefix + (root / 'backend/infrastructure/mpv/cinema.lua').read_text(encoding='utf-8') + checks, encoding='utf-8')
    result = subprocess.run([binary, '--no-config', '--vo=null', '--ao=null', '--idle=yes', f'--script={script}'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Segment OSD checks passed' in result.stdout, result.stdout + result.stderr
