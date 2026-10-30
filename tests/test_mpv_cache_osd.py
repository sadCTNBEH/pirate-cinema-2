"""Exercise range normalization and preview composition inside the shipped Lua runtime."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_cache_ranges_in_real_lua(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = root / 'mpv/mpv.com'
    mpv = str(binary) if binary.is_file() else shutil.which('mpv')
    if not mpv:
        pytest.skip('Host MPV unavailable')
    prefix = r'''
local runtime=require 'mp'
local quit=runtime.commandv
local observers,events,messages={},{},{}
runtime.observe_property=function(name,kind,fn) observers[name]=observers[name] or {}; table.insert(observers[name],fn) end
runtime.register_event=function(name,fn) events[name]=events[name] or {}; table.insert(events[name],fn) end
runtime.register_script_message=function(name,fn) messages[name]=fn end
'''
    checks = r'''
local ok,err=xpcall(function()
    local function ranges(raw) return normalize_ranges({['seekable-ranges']=raw},100) end
    assert(#ranges({{start=10,['end']=20}})==1)
    local merged=ranges({{start=50,['end']=60},{start=0,['end']=10},{start=8,['end']=20},
        {start=90,['end']=200},{start=-1,['end']=4},{start=5,['end']=5},
        {start=0/0,['end']=50},{start=2,['end']=math.huge},{start='1',['end']=5},false})
    assert(#merged==3 and merged[1].start==0 and merged[1].finish==20)
    assert(merged[2].start==50 and merged[2].finish==60 and merged[3].finish==100)
    assert(#normalize_ranges(nil,100)==0 and #normalize_ranges({},0)==0)
    mp.get_property_number=function(name,fallback) if name=='duration' then return 100 end; return fallback end
    mp.get_property_native=function(name,fallback)
        if name=='demuxer-cache-state' then return {['seekable-ranges']={{start=10,['end']=20},{start=40,['end']=60}}} end
        if name=='duration' then return 100 end
        return fallback
    end
    for _,fn in ipairs(events['file-loaded']) do fn() end
    assert(#cached_ranges==2)
    for _,fn in ipairs(events['start-file']) do fn() end
    assert(#cached_ranges==0 and not cache_file_ready)
    for _,fn in ipairs(observers['demuxer-cache-state']) do fn(nil,{['seekable-ranges']={{start=0,['end']=100}}}) end
    assert(#cached_ranges==0,'old observations ignored before file-loaded')
    for _,fn in ipairs(events['file-loaded']) do fn() end
    assert(#cached_ranges==2)
    for _,fn in ipairs(events['end-file']) do fn() end
    assert(#cached_ranges==0)
    -- Real ASS composition; no bitmap paths or overlay-add command.
    mp.get_osd_size=function() return 960,540,1 end
    mp.get_mouse_pos=function() return 480,476 end
    mp.get_property_native=function(name,fallback)
        if name=='duration' then return 100 elseif name=='time-pos' then return 5 end
        return fallback
    end
    overlay.update=function() end
    thumbnail_overlay.update=function() end
    thumbnail_overlay.remove=function() end
    render()
    preview.time=50; preview.bucket=50
    messages['cinema-preview-result'](tostring(preview.serial),'[["FFFFFF","m 0 0 l 112 0 112 63 0 63"]]')
    local a=ass.ass_new(); draw_preview(a,0)
    assert(thumbnail_overlay.data:find('112 63',1,true),'RAM vector preview composed')
    assert(not thumbnail_overlay.data:find('bgra',1,true))
    clear_preview(); assert(not preview.path and not preview.shown)
end,debug.traceback)
if ok then print('RAM cache OSD checks passed') else print(err) end
quit('quit',ok and 0 or 1)
'''
    script = tmp_path / 'cache-test.lua'
    script.write_text(prefix+(root/'backend/infrastructure/mpv/cinema.lua').read_text(encoding='utf-8')+checks,
                      encoding='utf-8')
    result = subprocess.run([mpv,'--no-config','--vo=null','--ao=null','--idle=yes',f'--script={script}'],
                            capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15,check=False)
    assert result.returncode==0, result.stdout+result.stderr
    assert 'RAM cache OSD checks passed' in result.stdout, result.stdout+result.stderr
