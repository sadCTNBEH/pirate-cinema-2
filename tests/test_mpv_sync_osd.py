"""Exercise native OSD layout, hit regions and delay actions in bundled MPV."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('size', [(960, 540), (420, 300), (320, 240)])
def test_native_osd_sync_layout(tmp_path, size):
    root = Path(__file__).resolve().parents[1]
    binary = root / 'mpv/mpv.com'
    if not binary.is_file():
        pytest.skip('Bundled MPV unavailable')
    prefix = r'''
local runtime=require 'mp'
local quit=runtime.commandv
local handlers,messages={},{}
runtime.add_forced_key_binding=function(_,name,fn) handlers[name]=fn end
runtime.register_script_message=function(name,fn) messages[name]=fn end
'''
    checks = r'''
local ok,err=xpcall(function()
    local x,y=0,0
    local props={['sub-delay']=0,['audio-delay']=0,['track-list']={}}
    for i=1,22 do
        props['track-list'][#props['track-list']+1]={id=i,type='sub',lang=i%2==0 and 'eng' or 'rus',title=string.rep('Длинное название релиза ',8),selected=i==2}
    end
    props['track-list'][#props['track-list']+1]={id=1,type='audio',lang='rus',title='Озвучка',selected=true}
    mp.get_osd_size=function() return SIZE_W,SIZE_H,1 end
    mp.get_mouse_pos=function() return x,y end
    mp.get_property_native=function(name,fallback) if props[name]~=nil then return props[name] end return fallback end
    mp.commandv=function(name,event,payload)
        if name=='script-message' and event=='cinema-action' then
            local cmd=utils.parse_json(payload)
            if cmd[1]=='set_property' then props[cmd[2]]=cmd[3]
            elseif cmd[1]=='add' then props[cmd[2]]=(props[cmd[2]] or 0)+cmd[3] end
        end
    end
    overlay.update=function() end
    local function bounded()
        for _,r in ipairs(regions) do
            assert(r.x>=0 and r.y>=0 and r.x+r.w<=width and r.y+r.h<=height,'hit region outside viewport')
        end
        for i,r in ipairs(regions) do for j,s in ipairs(regions) do
            if i<j then
                local overlap=math.min(r.x+r.w,s.x+s.w)-math.max(r.x,s.x)>0.1 and math.min(r.y+r.h,s.y+s.h)-math.max(r.y,s.y)>0.1
                assert(not overlap,'overlapping hit regions: '..i..' '..j)
            end
        end end
    end
    render(); bounded()
    toggle_menu('sub'); render(); bounded()
    assert(overlay.data:find('…',1,true),'long labels must ellipsize')
    assert(overlay.data:find('✓',1,true),'active track must be marked')
    local total=#track_rows('sub')
    assert(total==24,'all tracks, Off, external search preserved')
    menu_input('RIGHT'); render(); bounded(); assert(page==1,'pagination works')
    menu_input('ESC'); render(); assert(not menu,'Escape closes menu')
    toggle_menu('sync'); render(); bounded()
    local function press(key) menu_input(key); render() end
    press('ENTER'); assert(props['sub-delay']==-0.5,'subtitle decrement')
    press('DOWN'); press('ENTER'); assert(props['sub-delay']==0,'subtitle increment')
    press('DOWN'); press('ENTER'); assert(props['sub-delay']==0,'subtitle reset')
    press('DOWN'); press('ENTER'); assert(props['audio-delay']==-0.5,'audio decrement')
    press('DOWN'); press('ENTER'); assert(props['audio-delay']==0,'audio increment')
    press('DOWN'); press('ENTER'); assert(props['audio-delay']==0,'audio reset')
    toggle_menu('sub'); render(); menu_focus=1; menu_input('ENTER'); render()
    assert(props.sid=='no','Off action uses sid=no')
    toggle_menu('audio'); render(); bounded(); menu_focus=2; menu_input('ENTER'); render()
    assert(props.aid==1,'audio track selection')
end,debug.traceback)
if ok then print('OSD sync layout passed') else print(err) end
quit('quit',ok and 0 or 1)
'''.replace('SIZE_W', str(size[0])).replace('SIZE_H', str(size[1]))
    script = tmp_path / 'sync_layout.lua'
    script.write_text(prefix + (root / 'backend/infrastructure/mpv/cinema.lua').read_text(encoding='utf-8') + checks, encoding='utf-8')
    result = subprocess.run([str(binary), '--no-config', '--vo=null', '--ao=null', '--idle=yes', f'--script={script}'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_mpv_tracks_and_delays(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = root / 'mpv/mpv.com'
    ffmpeg = shutil.which('ffmpeg')
    if not binary.is_file() or not ffmpeg:
        pytest.skip('MPV/ffmpeg unavailable')
    video = tmp_path / 'fixture.mkv'
    sub = tmp_path / 'test.srt'
    sub.write_text('1\n00:00:00,000 --> 00:00:02,000\nТест\n', encoding='utf-8')
    ass = tmp_path / 'test.ass'
    ass.write_text('[Script Info]\nScriptType: v4.00+\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,Test\n', encoding='utf-8')
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=320x240:r=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=440', '-f', 'lavfi', '-i', 'sine=frequency=880',
                    '-i', str(sub), '-map', '0:v', '-map', '1:a', '-map', '2:a', '-map', '3:s',
                    '-t', '3', '-c:v', 'mpeg4', '-c:a', 'aac', '-c:s', 'srt', str(video)], check=True, timeout=20)
    script = tmp_path / 'real.lua'
    script.write_text(r'''
local mp=require 'mp'
mp.register_event('file-loaded',function()
 local ok,err=xpcall(function()
  mp.commandv('sub-add',SUB_PATH,'select','Russian external')
  mp.set_property_number('aid',2)
  mp.set_property_number('sub-delay',-0.5)
  mp.set_property_number('audio-delay',0.5)
  assert(mp.get_property_number('aid')==2)
  assert(mp.get_property_number('sub-delay')==-0.5)
  assert(mp.get_property_number('audio-delay')==0.5)
  assert(mp.get_property_number('sid')==2)
  mp.commandv('sub-add',ASS_PATH,'select','ASS external')
  assert(mp.get_property_number('sid')==3)
  local count=0
  for _,track in ipairs(mp.get_property_native('track-list')) do if track.type=='sub' then count=count+1 end end
  assert(count==3,'embedded subtitle and both external tracks preserved')
  mp.set_property_number('sid',1); assert(mp.get_property_number('sid')==1)
  mp.set_property('sid','no'); assert(mp.get_property('sid')=='no')
  mp.set_property_number('sub-delay',0); mp.set_property_number('audio-delay',0)
 end,debug.traceback)
 if ok then print('Real tracks and delays passed') else print(err) end
 mp.commandv('quit',ok and 0 or 1)
end)
'''.replace('SUB_PATH', '[[' + sub.as_posix() + ']]').replace('ASS_PATH', '[[' + ass.as_posix() + ']]'), encoding='utf-8')
    result = subprocess.run([str(binary), '--no-config', '--vo=null', '--ao=null', f'--script={script}', str(video)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, check=False)
    assert result.returncode == 0 and 'Real tracks and delays passed' in result.stdout, result.stdout + result.stderr
