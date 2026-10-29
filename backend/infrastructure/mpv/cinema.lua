-- MPV owns playback state and composites this interface over its native video.
-- All playback actions return through the existing Python service over IPC.
local mp = require 'mp'
local ass = require 'mp.assdraw'
local utils = require 'mp.utils'
local overlay = mp.create_osd_overlay('ass-events')
local visible, menu, page, drag = true, nil, 0, nil
local has_next = false
local continuation, continuation_focus, continuation_page = {}, 1, 0
local continuation_keys = {'ENTER','ESC','UP','DOWN'}
local casting = {connected=false, devices={}}
local fade_started = nil
local last_drag_action = 0
local regions, width, height, scale = {}, 960, 540, 1
local dirty = true
local render, activity
local hide_timer, fade_timer, progress_timer
local hovered_region = nil
local cursor_mode = nil
local background_click = nil
local preview = {serial=0, bucket=nil, time=nil, x=nil, path=nil, path_bucket=nil, shown=nil, requested=false}
local preview_timer
local preview_mode='local'
local seek_target, seek_pending, seek_deadline = nil,nil,0
local segment_data, auto_skip = {}, false
local active_segment, countdown, cancelled, skipped = nil, nil, {}, {}
local chapter_names = {intro='intro', opening='intro', ['Заставка']='intro', ['заставка']='intro',
    recap='recap', ['previously on']='recap', ['Ранее']='recap', ['ранее']='recap',
    credits='outro', ending='outro', ['Титры']='outro', ['титры']='outro',
    preview='preview', ['next episode']='preview', ['Анонс']='preview', ['анонс']='preview'}
local function finite(n) return type(n)=='number' and n==n and math.abs(n)<math.huge end
local function chapters()
    local raw=mp.get_property_native('chapter-list',{})
    local duration=mp.get_property_number('duration',0)
    local rows={}
    for i,c in ipairs(raw) do
        if not finite(c.time) or c.time<0 or c.time>=duration or (i>1 and c.time<=raw[i-1].time) then return {} end
        rows[#rows+1]={time=c.time,title=c.title or ('Глава '..i),kind=chapter_names[(c.title or ''):match('^%s*(.-)%s*$'):lower()]}
    end
    return rows
end
local function chapter_segments()
    local rows, intervals=chapters(),{}
    for i,c in ipairs(rows) do
        if c.kind and rows[i+1] then
            intervals[#intervals+1]={kind=c.kind,start=c.time,['end']=rows[i+1].time,source='chapter'}
        end
    end
    return intervals
end
local function current_segment()
    if casting.connected then return nil end
    local position=mp.get_property_number('time-pos',-1)
    local duration=mp.get_property_number('duration',0)
    local local_segments=chapter_segments()
    for _,list in ipairs({segment_data,local_segments}) do
        for _,s in ipairs(list) do
            if finite(s.start) and finite(s['end']) and s.start>=0 and s.start<s['end'] and s['end']<=duration
                and position>=s.start and position<s['end'] then
                local safe=false
                if s.source=='introdb' then
                    -- Community confidence cannot establish the edit of this torrent release.
                    for _,c in ipairs(local_segments) do
                        if c.kind==s.kind and math.abs(c.start-s.start)<=1 and math.abs(c['end']-s['end'])<=1 then safe=true end
                    end
                end
                return {kind=s.kind,start=s.start,['end']=s['end'],source=s.source,auto=safe,
                    key=s.kind..':'..s.start..':'..s['end']}
            end
        end
    end
end
local function skip_segment()
    local s=current_segment()
    if not s or skipped[s.key] then return end
    skipped[s.key]=true; countdown=nil
    mp.commandv('script-message','cinema-action',utils.format_json({'cinema-seek',s['end']}))
    dirty=true
end
-- Keep the real Windows cursor visible over the cross-process HWND.
-- Never render the pointer in OSD: that ties its motion to video presentation.
local windows_native_cursor = package.config:sub(1,1)=='\\'
local function show_cursor(show, force)
    local mode = (windows_native_cursor or show) and 'no' or 'always'
    if force or cursor_mode~=mode then
        mp.set_property('cursor-autohide',mode)
        cursor_mode=mode
    end
end
local function action(cmd)
    mp.commandv('script-message', 'cinema-action', utils.format_json(cmd))
end
local function continue_action(kind,index)
    action({'continuation',kind,continuation.token,index})
end
local function continuation_choices()
    local choices={}
    if continuation.status=='offer' then
        choices[#choices+1]={label=continuation.external and 'Найти раздачу' or 'Смотреть',kind='watch'}
    elseif continuation.status=='results' then
        for i,r in ipairs(continuation.results or {}) do
            local size=r.size and string.format('%.1f ГБ',r.size/1073741824) or 'Размер неизвестен'
            choices[#choices+1]={label=r.title,detail=(r.quality or 'Качество неизвестно')..' · '..size..' · Сиды: '..tostring(r.seeders or '?'),kind='choose',index=i-1}
        end
    elseif continuation.status=='files' then
        for i,f in ipairs(continuation.files or {}) do
            choices[#choices+1]={label=f.path or f.name,kind='file',index=i-1}
        end
    elseif continuation.status=='empty' then
        choices[#choices+1]={label='Повторить поиск',kind='retry'}
    end
    choices[#choices+1]={label='Отмена',kind='cancel'}
    return choices
end
local function value(name, fallback)
    if casting.connected then
        local mapped = {['time-pos']=casting.position, pause=casting.paused}
        if mapped[name] ~= nil then return mapped[name] end
    end
    return mp.get_property_native(name, fallback)
end
local function clock(n)
    n = math.max(0, math.floor(tonumber(n) or 0))
    if n >= 3600 then return string.format('%d:%02d:%02d', n/3600, (n/60)%60, n%60) end
    return string.format('%02d:%02d', n/60, n%60)
end
local function mouse()
    local x, y = mp.get_mouse_pos()
    return x / scale, y / scale
end
local function hit(x, y, r) return x >= r.x and x <= r.x+r.w and y >= r.y and y <= r.y+r.h end
local function rect(a, x, y, w, h, color, alpha)
    a:new_event()
    a:append(string.format('{\\an7\\bord0\\shad0\\1c&H%s&\\1a&H%02X&}', color or '15110F', alpha or 0))
    a:pos(0, 0); a:draw_start(); a:rect_cw(x, y, x+w, y+h); a:draw_stop()
end
local function text(a, x, y, label, size, alpha, align, clip)
    -- Escape locally: the bundled MPV predates the escape-ass command.
    local escaped = tostring(label):gsub('[\r\n]', ' '):gsub('\\', '\\\239\187\191'):gsub('{', '\\{'):gsub('}', '\\}')
    a:new_event()
    a:append(string.format('{%s\\an%d\\pos(%.1f,%.1f)\\fnSegoe UI\\fs%d\\bord0\\shad0\\1c&HFFFFFF&\\1a&H%02X&}%s',
        clip or '', align or 4, x, y, size or 16, alpha or 0, escaped))
end
local function region(x, y, w, h, fn, kind)
    regions[#regions+1] = {x=x,y=y,w=w,h=h,fn=fn,kind=kind}
end
local function button(a, x, y, w, label, fn, alpha, h)
    h = h or 32
    local mx, my = mouse()
    if hit(mx,my,{x=x,y=y,w=w,h=h}) then rect(a,x,y,w,h,'FFFFFF',math.max(alpha,210)) end
    text(a,x+w/2,y+h/2,label,17,alpha,5,string.format('\\clip(%.0f,%.0f,%.0f,%.0f)',x,y,x+w,y+h))
    region(x,y,w,h,fn)
end
local function cast_icon(a, x, y, alpha)
    -- Screen outline and broadcast waves, drawn in ASS rather than a font glyph.
    rect(a,x,y,24,2,'FFFFFF',alpha)
    rect(a,x,y,2,7,'FFFFFF',alpha)
    rect(a,x+22,y,2,18,'FFFFFF',alpha)
    rect(a,x+14,y+16,10,2,'FFFFFF',alpha)
    for _,radius in ipairs({5,10,15}) do
        local outer, inner = {}, {}
        for i=0,12 do
            local angle=i*math.pi/24
            outer[#outer+1]={x+radius*math.cos(angle),y+18-radius*math.sin(angle)}
            inner[#inner+1]={x+(radius-2)*math.cos(angle),y+18-(radius-2)*math.sin(angle)}
        end
        a:new_event()
        a:append(string.format('{\\an7\\bord0\\shad0\\1c&HFFFFFF&\\1a&H%02X&}',alpha))
        a:pos(0,0); a:draw_start()
        a:move_to(outer[1][1],outer[1][2])
        for _,p in ipairs(outer) do a:line_to(p[1],p[2]) end
        for i=#inner,1,-1 do a:line_to(inner[i][1],inner[i][2]) end
        a:draw_stop()
    end
end
local function toggle_menu(name)
    menu = menu ~= name and name or nil
    page = 0
    dirty = true
    activity()
end
local function track_rows(kind)
    local rows = {{label=kind == 'audio' and 'Автоматически' or 'Выключены', command={'set_property',kind == 'audio' and 'aid' or 'sid',kind == 'audio' and 'auto' or 'no'}}}
    for _, track in ipairs(value('track-list', {})) do
        if track.type == kind then
            rows[#rows+1] = {label=(track.selected and '✓  ' or '') .. (track.title or track.lang or ('Дорожка ' .. track.id)),
                command={'set_property', kind == 'audio' and 'aid' or 'sid',track.id}}
        end
    end
    return rows
end
local function seek_at(x)
    local duration = value('duration', 0)
    if duration > 0 then
        seek_target=math.max(0,math.min(1,(x-24)/math.max(1,width-48)))*duration
        dirty=true
    end
end
local function commit_seek(x)
    seek_at(x)
    if seek_target then
        seek_pending=seek_target; seek_deadline=mp.get_time()+3
        action({'cinema-seek',seek_target})
    end
    seek_target=nil; dirty=true
end
local function volume_at(x)
    action({'set_property','volume',math.floor(math.max(0,math.min(100,x-254)))})
end
local function remove_thumbnail()
    if preview.shown then mp.commandv('overlay-remove',42); preview.shown=nil end
end
local function clear_preview()
    preview_timer:kill()
    if preview.requested then mp.commandv('script-message','cinema-preview') end
    preview.serial=preview.serial+1
    preview.bucket=nil; preview.time=nil; preview.path=nil; preview.path_bucket=nil; preview.requested=false; preview.buffered=nil
    remove_thumbnail()
end
local function preview_position(x)
    local duration=value('duration',0)
    return math.max(0,math.min(math.max(0,duration-0.05),
        math.max(0,math.min(1,(x-24)/math.max(1,width-48)))*duration))
end
local function update_preview(x,y)
    if menu or not visible or value('duration',0)<=0 or width<280 or height<230
        or not hit(x,y,{x=24,y=height-76,w=width-48,h=28}) then
        if preview.time then clear_preview(); dirty=true end
        return
    end
    local position=preview_position(x)
    if preview.x~=math.floor(x) or not preview.time or math.floor(position*10)~=math.floor(preview.time*10) then dirty=true end
    preview.x=math.floor(x); preview.time=position
    local interval=preview_mode=='stream' and 10 or 5
    local bucket=math.floor(position/interval)*interval
    if bucket~=preview.bucket then
        if preview.requested then mp.commandv('script-message','cinema-preview') end
        preview.serial=preview.serial+1; preview.bucket=bucket; preview.requested=false; preview.buffered=nil
        preview_timer:kill(); preview_timer:resume()
    end
end
preview_timer=mp.add_timeout(0.18,function()
    if preview.time and not menu and visible then
        preview.requested=true
        mp.commandv('script-message','cinema-preview',tostring(preview.serial),tostring(preview.bucket))
    end
end)
preview_timer:kill()
local function draw_preview(a,alpha)
    local mx,my=mouse()
    update_preview(mx,my)
    if not preview.time or fade_started then remove_thumbnail(); return end
    local pw,ph=224/scale,126/scale
    local x=math.max(8,math.min(width-pw-8,preview.x-pw/2))
    local bottom=height-96
    local has_image=preview.path~=nil and preview.bucket==preview.path_bucket
        and height-ph>150 and width*scale>=240
    if not has_image then remove_thumbnail(); return end
    local px,py=math.floor(x*scale),math.floor((bottom-28-ph)*scale)
    local signature=preview.path..':'..px..':'..py
    if signature~=preview.shown then
        mp.commandv('overlay-add',42,px,py,preview.path,0,'bgra',224,126,224*4)
        preview.shown=signature
    end
    local tw=76
    local tx=math.max(8,math.min(width-tw-8,preview.x-tw/2))
    a:new_event()
    a:append(string.format('{\\an7\\bord0\\shad0\\1c&H100C0A&\\1a&H%02X&}',alpha))
    a:pos(0,0); a:draw_start(); a:round_rect_cw(tx,bottom-27,tx+tw,bottom-1,5); a:draw_stop()
    text(a,tx+tw/2,bottom-14,clock(preview.time),14,alpha,5)
end
render = function()
    dirty = false
    if not visible then return end
    local w,h = mp.get_osd_size()
    if not w or w <= 0 or not h or h <= 0 then return end
    scale = math.max(0.65, math.min(h/540, w/720, 1.5))
    width, height = w/scale, h/scale
    overlay.res_x, overlay.res_y = width, height
    local alpha = fade_started and math.floor(255*math.min(1,(mp.get_time()-fade_started)/0.12)) or 0
    if alpha >= 255 then
        visible=false; fade_started=nil; hovered_region=nil
        clear_preview()
        show_cursor(false)
        fade_timer:kill(); overlay:remove(); return
    end
    local a = ass.ass_new()
    regions = {}
    for i=0,9 do rect(a,0,height-112+i*2,width,2,'100C0A',math.max(alpha,245-i*13)) end
    rect(a,0,height-92,width,92,'100C0A',math.max(alpha,35))
    rect(a,0,0,width,46,'100C0A',math.max(alpha,65))
    text(a,24,23,value('media-title','Pirate Cinema'),18,alpha,4,string.format('\\clip(24,0,%.0f,46)',width-190))
    button(a,width-182,7,40,'',function()
        toggle_menu('cast')
        if menu == 'cast' then
            casting.scanning=true
            action({'cast','discover'})
        end
    end,alpha)
    cast_icon(a,width-174,14,alpha)
    button(a,width-116,7,40,'',function() action({'cinema','pip'}) end,alpha)
    local px, py = width-108,14
    rect(a,px,py,24,2,'FFFFFF',alpha)
    rect(a,px,py+16,24,2,'FFFFFF',alpha)
    rect(a,px,py,2,18,'FFFFFF',alpha)
    rect(a,px+22,py,2,18,'FFFFFF',alpha)
    rect(a,px+12,py+8,8,6,'FFFFFF',alpha)
    button(a,width-56,7,40,'×',function() action({'cinema','close'}) end,alpha)
    local y = height-64
    local duration, position = value('duration',0), value('time-pos',0)
    if seek_pending and mp.get_time()>seek_deadline then seek_pending=nil end
    position=seek_target or seek_pending or position
    text(a,24,y-16,clock(position),14,alpha)
    text(a,width-24,y-16,clock(duration),14,alpha,6)
    rect(a,24,y,width-48,4,'FFFFFF',math.max(alpha,170))
    if duration > 0 then
        local fraction = math.max(0,math.min(1,position/duration))
        rect(a,24,y,(width-48)*fraction,4,'FFFFFF',alpha)
        rect(a,21+(width-48)*fraction,y-3,6,10,'FFFFFF',alpha)
    end
    region(24,y-12,width-48,28,seek_at,'seek')
    draw_preview(a,alpha)
    local current_chapter=nil
    for i,c in ipairs(chapters()) do
        if c.time<=position then current_chapter=i end
        local cx=24+(width-48)*c.time/duration
        rect(a,cx-1,y-2,2,8,'FFFFFF',alpha)
        local mx,my=mouse()
        if math.abs(mx-cx)<5 and math.abs(my-y)<12 then
            text(a,math.max(130,math.min(width-130,cx)),y-38,c.title,14,alpha,5)
        end
    end
    if #chapters()>0 then
        button(a,110,y-34,240,'Главы · '..((chapters()[current_chapter or 0] or {}).title or ''),function() toggle_menu('chapters') end,alpha,26)
    end
    if active_segment and not skipped[active_segment.key] then
        local labels={intro='Пропустить заставку',recap='Пропустить повтор',outro='Пропустить титры',preview='Пропустить анонс'}
        local label=labels[active_segment.kind]
        if countdown then label=label..' · '..math.max(1,math.ceil(8-countdown.elapsed)) end
        rect(a,width-300,height-164,276,38,'100C0A',12)
        button(a,width-300,height-164,276,label,skip_segment,0,38)
        if countdown then
            button(a,width-300,height-204,276,'Отменить автопропуск',function()
                cancelled[active_segment.key]=true; countdown=nil; dirty=true
            end,0,38)
        elseif active_segment.kind=='outro' and has_next then
            button(a,width-300,height-204,276,'Следующая серия',function() action({'cinema','next'}) end,0,38)
        end
    end
    if continuation.status then
        local choices=continuation_choices()
        local compact=continuation.status~='results' and continuation.status~='files'
        local count=math.min(4,#choices)
        local panel_w=math.min(compact and 360 or 560,width-48)
        local left=width-panel_w-24
        local top=compact and height-208 or math.max(54,height-150-56*count)
        rect(a,left,top,panel_w,compact and 88 or 62+56*count,'100C0A',4)
        local label=continuation.label or 'Следующая серия'
        if continuation.remaining then label=label..' · '..continuation.remaining..' с' end
        text(a,left+14,top+22,label,16,0,4,string.format('\\clip(%.0f,%.0f,%.0f,%.0f)',left,top,left+panel_w-12,top+40))
        if compact then
            local button_w=(panel_w-28)/#choices
            for i,choice in ipairs(choices) do
                local bx=left+14+(i-1)*button_w
                if i==continuation_focus then rect(a,bx,top+44,button_w-4,30,'FFFFFF',225) end
                button(a,bx,top+44,button_w-4,choice.label,function() continue_action(choice.kind,choice.index) end,0,30)
            end
        else
            continuation_page=math.floor((continuation_focus-1)/4)
            for n=1,count do
                local i=continuation_page*4+n
                local choice=choices[i]
                if choice then
                    local row_y=top+46+(n-1)*56
                    if i==continuation_focus then rect(a,left+8,row_y,panel_w-16,52,'FFFFFF',225) end
                    button(a,left+12,row_y,panel_w-24,choice.label,function() continue_action(choice.kind,choice.index) end,0,28)
                    if choice.detail then text(a,left+22,row_y+39,choice.detail,13,0,4) end
                end
            end
            if #choices>4 then
                button(a,left,top-28,100,'Назад',function() continuation_focus=math.max(1,continuation_focus-4); dirty=true end,0,26)
                button(a,left+panel_w-110,top-28,110,'Далее',function() continuation_focus=math.min(#choices,continuation_focus+4); dirty=true end,0,26)
            end
        end
    end
    y = height-45
    button(a,20,y,48,value('pause',false) and '▶' or 'Ⅱ',function() action({'cycle','pause'}) end,alpha)
    button(a,74,y,50,'−10',function() action({'seek',-10,'relative'}) end,alpha)
    button(a,128,y,50,'+10',function() action({'seek',10,'relative'}) end,alpha)
    button(a,192,y,52,value('mute',false) and 'Тихо' or 'Звук',function() action({'cycle','mute'}) end,alpha)
    local volume = math.max(0,math.min(100,value('volume',100)))
    rect(a,254,y+15,100,3,'FFFFFF',math.max(alpha,170))
    rect(a,254,y+15,volume,3,'FFFFFF',alpha)
    region(250,y,110,32,volume_at,'volume')
    button(a,width-284,y,64,'Аудио',function() toggle_menu('audio') end,alpha)
    button(a,width-216,y,100,'Субтитры',function() toggle_menu('sub') end,alpha)
    button(a,width-110,y,42,'···',function() toggle_menu('more') end,alpha)
    button(a,width-62,y,42,'⛶',function() action({'cinema','fullscreen'}) end,alpha)
    if value('paused-for-cache',false) then text(a,width/2,height/2,'Буферизация…',18,alpha,5) end
    if casting.connected then
        local status = casting.connection == 'connecting' and 'Подключение к ТВ…' or
            casting.connection == 'error' and 'Ошибка трансляции — откройте список ТВ' or
            casting.connection == 'paused' and 'На ТВ · пауза' or
            casting.connection == 'buffering' and 'На ТВ · загрузка' or 'На ТВ'
        text(a,width/2,60,status .. ' · ' .. (casting.device or ''),16,alpha,5,
            string.format('\\clip(12,46,%.0f,80)',width-12))
    end
    if menu then
        local rows = menu == 'audio' and track_rows('audio') or menu == 'sub' and track_rows('sub') or {
            {label='Скорость  ·  ' .. value('speed',1) .. '×', fn=function() toggle_menu('speed') end},
            {label='Субтитры  −0.5 с',command={'add','sub-delay',-0.5}},
            {label='Субтитры  +0.5 с',command={'add','sub-delay',0.5}},
        }
        if menu == 'cast' then
            rows = {{label='Обновить список ТВ', command={'cast','discover'}}}
            if casting.connected then
                table.insert(rows,1,{label=casting.connection == 'connecting' and 'Подключение…' or casting.connection == 'error' and 'Ошибка трансляции' or 'Подключено: ' .. (casting.device or 'ТВ'),fn=function() end})
                table.insert(rows,{label='Вернуться на ПК',command={'cast','return'}})
            else
                for _,device in ipairs(casting.devices or {}) do
                    table.insert(rows,{label=device.name .. ' · ' .. device.kind,command={'cast',device.id}})
                end
            end
            if casting.error then table.insert(rows,{label=casting.error,fn=function() end}) end
            if casting.scanning then
                table.insert(rows,1,{label='Поиск телевизоров…',fn=function() end})
            elseif #rows == 1 then table.insert(rows,{label='ТВ не найдены. Проверьте Wi-Fi.',fn=function() end}) end
        end
        if menu == 'more' and has_next then
            table.insert(rows,1,{label='Следующая серия', command={'cinema','next'}})
        end
        if menu=='more' and #chapters()>0 then
            table.insert(rows,1,{label='Главы',fn=function() toggle_menu('chapters') end})
        end
        if menu=='more' then
            table.insert(rows,{label=(auto_skip and '✓  ' or '')..'Автопропуск заставок',fn=function()
                auto_skip=not auto_skip; countdown=nil
                action({'cinema','auto-skip',auto_skip}); dirty=true
            end})
        end
        if menu=='chapters' then
            rows={}
            for i,c in ipairs(chapters()) do
                rows[#rows+1]={label=(i==current_chapter and '✓  ' or '')..clock(c.time)..'  '..c.title,command={'cinema-seek',c.time}}
            end
            if #rows==0 then menu=nil; page=0; dirty=true; return end
        end
        if menu == 'speed' then
            rows = {}
            for _,speed in ipairs({0.5,0.75,1,1.25,1.5,2}) do rows[#rows+1] = {label=speed .. '×',command={'set_property','speed',speed}} end
        end
        local row_h, mw = 28, 248
        local page_size=math.max(1,math.min(6,math.floor((height-190)/row_h)))
        page=math.min(page,math.floor((#rows-1)/page_size))
        local count = math.min(page_size,#rows-page*page_size)
        local paginated = #rows > page_size
        local footer_h = paginated and row_h or 0
        local x, top = width-mw-24,height-108-count*row_h
        rect(a,x,top-28,mw,count*row_h+28+footer_h,'100C0A',math.max(alpha,12))
        text(a,x+12,top-14,menu == 'chapters' and 'Главы' or menu == 'audio' and 'Аудиодорожки' or menu == 'sub' and 'Субтитры' or menu == 'speed' and 'Скорость' or 'Настройки',16,alpha)
        button(a,x+mw-32,top-28,28,'×',function() menu=nil; activity() end,alpha,28)
        for i=1,count do
            local row=rows[page*page_size+i]
            button(a,x+6,top+(i-1)*row_h,mw-12,row.label,function()
                if row.fn then row.fn() else
                    action(row.command)
                    if menu ~= 'cast' then menu=nil end
                    activity()
                end
            end,alpha,row_h)
        end
        if paginated then
            if page > 0 then button(a,x+6,top+count*row_h,48,'‹',function() page=page-1; activity() end,alpha,row_h) end
            text(a,x+mw/2,top+count*row_h+row_h/2,(page+1)..' / '..math.ceil(#rows/page_size),14,alpha,5)
            if (page+1)*page_size < #rows then button(a,x+mw-54,top+count*row_h,48,'›',function() page=page+1; activity() end,alpha,row_h) end
        end
    end
    overlay.data = a.text
    overlay:update()
end
activity = function()
    if not visible or fade_started then dirty=true end
    visible=true; fade_started=nil
    show_cursor(true)
    fade_timer:kill()
    hide_timer:kill(); hide_timer:resume()
end
local function begin_hide()
    if continuation.status or not visible or menu or drag or preview.time or (active_segment and not skipped[active_segment.key]) then return end
    fade_started=mp.get_time()
    dirty=true
    fade_timer:resume()
end
-- Interaction is rendered at the next MPV idle callback, never behind a progress timer.
fade_timer=mp.add_periodic_timer(1/60,function() dirty=true end)
fade_timer:kill()
hide_timer=mp.add_timeout(2.5,begin_hide)
progress_timer=mp.add_timeout(0.1,function() if visible then dirty=true end end)
progress_timer:kill()
mp.register_idle(function() if dirty then render() end end)
mp.add_forced_key_binding('mouse_move','cinema-move',function()
    activity()
    local x,y=mouse()
    update_preview(x,y)
    local hovered=nil
    for i=#regions,1,-1 do if hit(x,y,regions[i]) then hovered=i; break end end
    if hovered~=hovered_region then hovered_region=hovered; dirty=true end
    if drag=='seek' then seek_at(x)
    elseif drag and mp.get_time()-last_drag_action>=0.08 then
        last_drag_action=mp.get_time()
        volume_at(x)
    end
end)
mp.add_forced_key_binding('mouse_leave','cinema-leave',function()
    clear_preview()
    drag=nil; seek_target=nil; menu=nil; hovered_region=nil; dirty=true
    hide_timer:kill(); begin_hide()
end)
mp.add_forced_key_binding('MBTN_LEFT','cinema-click',function(event)
    if event.event=='up' then
        if drag then local x=mouse(); if drag=='seek' then commit_seek(x) else volume_at(x) end end
        drag=nil; activity(); return
    end
    if event.event~='down' and event.event~='press' then return end
    local was_visible=visible and not fade_started
    activity()
    -- Refresh geometry before hit testing, including the first click after hiding.
    if dirty then render() end
    local x,y=mouse()
    for i=#regions,1,-1 do
        local r=regions[i]
        if hit(x,y,r) then
            background_click=nil; drag=r.kind
            if drag=='seek' then seek_pending=nil end
            r.fn(x)
            if event.event=='press' and drag=='seek' then commit_seek(x); drag=nil end
            dirty=true; return
        end
    end
    if menu then menu=nil; background_click=nil; dirty=true; return end
    -- Detect double clicks only on the image: buttons retain immediate independent clicks.
    local now=mp.get_time()
    if background_click and now-background_click.time<=0.3
        and math.abs(x-background_click.x)<=20 and math.abs(y-background_click.y)<=20 then
        if background_click.toggled then action({'set_property','pause',background_click.paused}) end
        background_click=nil
        action({'cinema','fullscreen'})
        return
    end
    background_click={time=now,x=x,y=y,paused=value('pause',false),toggled=was_visible}
    if was_visible then action({'cycle','pause'}) end
end,{complex=true})
mp.add_forced_key_binding('MBTN_RIGHT','cinema-menu',function() toggle_menu('more') end)
mp.add_forced_key_binding('WHEEL_UP','cinema-volume-up',function() action({'add','volume',5}); activity() end)
mp.add_forced_key_binding('WHEEL_DOWN','cinema-volume-down',function() action({'add','volume',-5}); activity() end)
for _,prop in ipairs({'time-pos','duration','pause','volume','mute','track-list','chapter-list','chapter','aid','sid','media-title','speed','paused-for-cache','osd-dimensions','fullscreen'}) do
    mp.observe_property(prop,'native',function()
        if prop=='time-pos' then
            if seek_pending and math.abs(value('time-pos',0)-seek_pending)<1 then seek_pending=nil end
            if visible and not progress_timer:is_enabled() then progress_timer:resume() end
            return
        end
        dirty=true
        if prop=='fullscreen' or prop=='osd-dimensions' then show_cursor(true,true) end
        if prop=='pause' or prop=='volume' or prop=='mute' or prop=='speed' or prop=='osd-dimensions' or prop=='fullscreen' then activity() end
    end)
end
-- Playback progress is capped at 10 Hz; hidden controls do not schedule redraws.
mp.register_event('file-loaded',function() clear_preview(); seek_target=nil; seek_pending=nil; drag=nil; menu=nil; page=0; dirty=true; activity() end)
mp.register_event('end-file',function() clear_preview(); dirty=true end)
mp.register_script_message('cinema-preview-reset',function() clear_preview(); dirty=true end)
mp.register_script_message('cinema-preview-mode',function(mode) preview_mode=mode; dirty=true end)
mp.register_script_message('cinema-preview-result',function(serial,path)
    if serial~=tostring(preview.serial) or not preview.time then return end
    preview.requested=false
    preview.path=(path and path~='') and path or nil
    preview.path_bucket=preview.bucket
    dirty=true
end)
mp.observe_property('demuxer-cache-state','native',function(_,state)
    if preview_mode~='stream' or not preview.time then return end
    local buffered=false
    for _,range in ipairs((state or {})['seekable-ranges'] or {}) do
        if range.start and range['end'] and range.start<=preview.bucket and range['end']>preview.bucket+0.05 then buffered=true; break end
    end
    if buffered and not preview.buffered and not preview.path and not preview.requested
        and not preview_timer:is_enabled() then preview_timer:resume() end
    preview.buffered=buffered
end)
mp.register_script_message('cinema-continuation-input',function(key)
    if not continuation.status then return end
    if key=='confirm' then
        local c=continuation_choices()[continuation_focus]; if c then continue_action(c.kind,c.index) end
    elseif key=='up' or key=='left' then continuation_focus=math.max(1,continuation_focus-1)
    elseif key=='down' or key=='right' then continuation_focus=math.min(#continuation_choices(),continuation_focus+1) end
    activity(); dirty=true
end)
mp.register_script_message('cinema-continuation',function(payload)
    local data=utils.parse_json(payload) or {}
    if data.token~=continuation.token or data.status~=continuation.status then continuation_focus=1 end
    continuation=data
    for _,key in ipairs(continuation_keys) do mp.remove_key_binding('cinema-continue-'..key) end
    if data.status then
        mp.add_forced_key_binding('ENTER','cinema-continue-ENTER',function()
            local c=continuation_choices()[continuation_focus]; if c then continue_action(c.kind,c.index) end
        end)
        mp.add_forced_key_binding('ESC','cinema-continue-ESC',function() continue_action('cancel') end)
        mp.add_forced_key_binding('UP','cinema-continue-UP',function() continuation_focus=math.max(1,continuation_focus-1); dirty=true end)
        mp.add_forced_key_binding('DOWN','cinema-continue-DOWN',function() continuation_focus=math.min(#continuation_choices(),continuation_focus+1); dirty=true end)
        activity()
    end
    dirty=true
end)
mp.register_script_message('cinema-next',function(available) has_next=available=='yes'; dirty=true end)
mp.register_script_message('cinema-segments',function(payload)
    local data=utils.parse_json(payload)
    if not data or data.path~=mp.get_property('path') then return end
    segment_data=data.segments or {}; auto_skip=data.auto==true; dirty=true
end)
mp.register_script_message('cinema-auto-skip',function(enabled)
    auto_skip=enabled=='yes'; countdown=nil; dirty=true
end)
mp.register_event('start-file',function()
    continuation={}; for _,key in ipairs(continuation_keys) do mp.remove_key_binding('cinema-continue-'..key) end
    segment_data={}; active_segment=nil; countdown=nil; cancelled={}; skipped={}; has_next=false
    menu=nil; page=0; dirty=true
end)
mp.register_event('file-loaded',function() mp.commandv('script-message','cinema-segments-request') end)
mp.register_event('seek',function()
    if active_segment then cancelled[active_segment.key]=true end
    countdown=nil
end)
local segment_timer=mp.add_periodic_timer(0.1,function()
    local s=current_segment()
    local previous=active_segment and active_segment.key
    active_segment=s
    if not s or s.key~=previous then
        countdown=nil
        if s and not skipped[s.key] then
            activity()
            if s.kind=='outro' then action({'cinema','suggest-next'}) end
        end
        if previous then dirty=true end
    end
    if s and not skipped[s.key] then
        if auto_skip and s.auto and (s.kind=='intro' or s.kind=='recap') and not cancelled[s.key] then
            countdown=countdown or {elapsed=0,last=mp.get_time()}
            local now=mp.get_time()
            if not value('pause',false) and not value('paused-for-cache',false) then
                countdown.elapsed=countdown.elapsed+math.min(0.25,now-countdown.last)
            end
            countdown.last=now
            if countdown.elapsed>=8 then skip_segment() end
        else countdown=nil end
        dirty=true
    end
end)
mp.register_script_message('cinema-fullscreen',function() show_cursor(true,true); dirty=true; activity() end)
mp.register_event('shutdown',function()
    clear_preview()
    hide_timer:kill(); fade_timer:kill(); progress_timer:kill()
    overlay:remove()
end)

mp.register_script_message('cinema-cast',function(payload)
    local previous_error=casting.error
    casting=utils.parse_json(payload) or {connected=false,devices={}}
    if casting.error and casting.error~=previous_error then
        mp.osd_message(casting.error,10)
        menu='cast'; page=0
    end
    dirty=true
    activity()
end)
