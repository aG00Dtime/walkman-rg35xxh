"""Walkman renderer: themes, visualiser, battery, large album art."""
import math
import os
import re
import time
import pygame

BG    = (20, 20, 19)
PANEL = (25, 25, 24)
LINE  = (65, 63, 56)
WHITE = (239, 231, 212)
MUTED = (151, 146, 134)
AMBER = (227, 173, 91)

THEMES = {
    'Cassette': dict(BG=(20,20,19), PANEL=(25,25,24), LINE=(65,63,56), WHITE=(239,231,212), MUTED=(151,146,134), ACCENT=(227,173,91)),
    'Midnight': dict(BG=(10,14,30), PANEL=(14,20,44), LINE=(38,52,90), WHITE=(200,220,255), MUTED=(100,125,170), ACCENT=(40,200,210)),
    'Forest':   dict(BG=(10,20,13), PANEL=(14,27,17), LINE=(38,72,45), WHITE=(205,240,205), MUTED=(100,150,110), ACCENT=(90,210,70)),
    'Neon':     dict(BG=(8,8,14),   PANEL=(14,10,24), LINE=(48,30,80), WHITE=(240,230,255), MUTED=(150,130,185), ACCENT=(255,55,200)),
    'Retro':    dict(BG=(28,20,16), PANEL=(38,28,20), LINE=(88,65,45), WHITE=(255,238,218), MUTED=(180,150,120), ACCENT=(255,100,30)),
    'Custom':   dict(BG=(20,20,19), PANEL=(25,25,24), LINE=(65,63,56), WHITE=(239,231,212), MUTED=(151,146,134), ACCENT=(227,173,91)),
}

class Design:
    def __init__(self, screen):
        self.s = screen
        path = os.path.join(os.path.dirname(__file__), 'font.ttf')
        self.fonts = {n: pygame.font.Font(path if os.path.isfile(path) else None, n) for n in (13, 15, 18, 20, 24, 28, 32)}
        self.set_theme('Cassette')
        self.shell = self.make_shell()

    def splash(self):
        self.s.fill(BG)
        # Reel pair
        for x in (220, 420):
            pygame.draw.circle(self.s,MUTED,(x,228),55,2)
            pygame.draw.circle(self.s,BG,(x,228),50)
            pygame.draw.circle(self.s,MUTED,(x,228),42)
            pygame.draw.circle(self.s,PANEL,(x,228),38)
            pygame.draw.circle(self.s,(17,18,17),(x,228),28)
            for i in range(6):
                a=i*math.tau/6
                pts=[]
                for r,off in ((24,-.18),(35,-.18),(35,.18),(24,.18)):
                    pts.append((x+math.cos(a+off)*r, 228+math.sin(a+off)*r))
                pygame.draw.polygon(self.s,AMBER,pts)
        # Tape window
        pygame.draw.rect(self.s,LINE,(262,196,116,60),1,border_radius=4)
        pygame.draw.rect(self.s,PANEL,(264,198,112,56),border_radius=3)
        # Tape path
        pygame.draw.line(self.s,AMBER,(220,278),(420,278),2)
        # Titles
        self.text('WALKMAN',320,100,32,WHITE,center=True)
        self.text('R G 3 5 X X _ H',320,138,18,AMBER,center=True)
        pygame.draw.line(self.s,LINE,(100,166),(540,166),1)
        self.text('Loading library...',320,370,15,MUTED,center=True)

    @staticmethod
    def _hsv_to_rgb(h, s, v):
        h = h % 360; i = int(h/60) % 6; f = h/60 - int(h/60)
        p, q, t = v*(1-s), v*(1-f*s), v*(1-(1-f)*s)
        r,g,b = [(v,t,p),(q,v,p),(p,v,t),(p,q,v),(t,p,v),(v,p,q)][i]
        return (int(r*255), int(g*255), int(b*255))

    def set_accent(self, color):
        global AMBER
        AMBER = color

    def set_theme(self, name, accent=None):
        global BG, PANEL, LINE, WHITE, MUTED, AMBER
        t = THEMES.get(name, THEMES['Cassette'])
        BG=t['BG']; PANEL=t['PANEL']; LINE=t['LINE']; WHITE=t['WHITE']; MUTED=t['MUTED']
        AMBER = accent if accent is not None else t['ACCENT']
        if hasattr(self, 'shell'): self.shell = self.make_shell()

    def text(self, value, x, y, size=18, color=None, width=None, center=False):
        if color is None: color = WHITE
        # Keep a decorative label from taking down the player if it asks for a
        # size outside the small set preloaded for this handheld.
        font = self.fonts.get(size, self.fonts[13])
        value = str(value)
        if width:
            while value and font.size(value)[0] > width:
                value = value[:-2] + '…' if not value.endswith('…') else value[:-2] + '…'
        im = font.render(value, True, color)
        self.s.blit(im, im.get_rect(center=(x,y)) if center else (x,y))

    def marquee(self, value, x, y, size, color, width, center=False):
        """Draw a single-line label that gently scrolls only when it is long."""
        font = self.fonts.get(size, self.fonts[13])
        value = str(value)
        image = font.render(value, True, color)
        if image.get_width() <= width:
            self.s.blit(image, (x + (width-image.get_width())//2 if center else x, y))
            return
        gap = 48
        period = image.get_width() + gap
        offset = int(time.monotonic() * 30) % period
        old_clip = self.s.get_clip()
        self.s.set_clip(pygame.Rect(x, y, width, image.get_height()))
        self.s.blit(image, (x - offset, y))
        self.s.blit(image, (x - offset + period, y))
        self.s.set_clip(old_clip)

    def line(self, a, b, color=None, w=1):
        pygame.draw.line(self.s, LINE if color is None else color, a, b, w)

    @staticmethod
    def _palette_color(palette, index, total):
        if not palette:
            return AMBER
        if len(palette) == 1 or total <= 1:
            return palette[0]
        point = index * (len(palette) - 1) / (total - 1)
        low = min(len(palette) - 2, int(point))
        mix = point - low
        first, second = palette[low], palette[low + 1]
        return tuple(int(first[i] + (second[i] - first[i]) * mix) for i in range(3))

    def icon(self, kind, x, y, color=None):
        if color is None: color = WHITE
        s = self.s
        if kind == 'Media':
            pygame.draw.rect(s,color,(x-27,y-19,40,38),3,border_radius=4)
            pygame.draw.polygon(s,color,[(x+13,y-10),(x+29,y-19),(x+29,y+19),(x+13,y+10)])
        elif kind in ('All Songs','Playlists'):
            pygame.draw.line(s,color,(x+8,y-19),(x+8,y+15),4)
            pygame.draw.line(s,color,(x+8,y-19),(x+27,y-24),5)
            pygame.draw.ellipse(s,color,(x-7,y+9,17,12))
            if kind=='All Songs':
                pygame.draw.line(s,color,(x+27,y-23),(x+27,y+9),4)
                pygame.draw.ellipse(s,color,(x+12,y+3,17,12))
            else:
                for dy in (-15,-3,9): pygame.draw.line(s,color,(x-25,y+dy),(x-7,y+dy),3)
        elif kind=='Albums':
            pygame.draw.circle(s,color,(x,y),25,3); pygame.draw.circle(s,color,(x,y),7,3)
            pygame.draw.arc(s,color,(x-18,y-18,36,36),0.5,1.6,2)
        elif kind=='Artists':
            pygame.draw.circle(s,color,(x,y-13),11,3)
            pygame.draw.arc(s,color,(x-24,y+2,48,39),0,math.pi,3)
            pygame.draw.line(s,color,(x-24,y+21),(x+24,y+21),3)
        elif kind=='Folders':
            pygame.draw.lines(s,color,True,[(x-25,y+20),(x-25,y-21),(x-9,y-21),(x-1,y-12),(x+26,y-12),(x+26,y+20)],3)
        elif kind=='Favorites':
            pts=[]
            for i in range(81):
                t=i*math.tau/80
                pts.append((x+int(1.65*16*math.sin(t)**3),y-int(1.65*(13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t)))))
            pygame.draw.lines(s,color,True,pts,3)
        elif kind=='Recent':
            pygame.draw.circle(s,color,(x,y),25,3); pygame.draw.lines(s,color,False,[(x,y-17),(x,y),(x+13,y)],3)
        else:
            pts=[]
            for i in range(48):
                a=i*math.tau/48; r=27 if i%6 in (1,2,3,4) else 22
                pts.append((x+int(math.cos(a)*r),y+int(math.sin(a)*r)))
            pygame.draw.lines(s,color,True,pts,3); pygame.draw.circle(s,color,(x,y),10,3)

    def hints(self, entries):
        self.line((22,437),(618,437))
        for (key,label),x in zip(entries,(25,258,483)):
            if len(key)>1:
                pygame.draw.rect(self.s,WHITE,(x,449,55,22),1,border_radius=11)
                self.text(key,x+27,460,13,WHITE,center=True); self.text(label,x+64,451,15)
            else:
                pygame.draw.circle(self.s,WHITE,(x+11,460),12,1); self.text(key,x+11,460,15,WHITE,center=True); self.text(label,x+32,451,15)

    def _draw_battery(self, pct, x, y):
        bw, bh, nw, nh = 32, 14, 4, 8
        fill_color = (220, 70, 60) if pct <= 20 else AMBER
        pygame.draw.rect(self.s, MUTED, (x, y-bh//2, bw, bh), 1, border_radius=3)
        pygame.draw.rect(self.s, MUTED, (x+bw, y-nh//2, nw, nh), border_radius=2)
        fw = max(0, int((bw-4) * pct / 100))
        if fw: pygame.draw.rect(self.s, fill_color, (x+2, y-bh//2+2, fw, bh-4), border_radius=2)

    def header(self, title='WALKMAN RG35XX_H', app=None):
        self.s.fill(BG); self.text(title,23,17,18)
        batt=getattr(app,'_battery',None)
        if batt is not None: self._draw_battery(batt,596,21)
        else: self.text('LIBRARY',614,21,13,MUTED,center=True)
        self.line((22,51),(618,51))

    def transport(self,x,y,paused=False):
        if paused: pygame.draw.polygon(self.s,WHITE,[(x-7,y-10),(x-7,y+10),(x+10,y)])
        else:
            for dx in (-7,3): pygame.draw.rect(self.s,WHITE,(x+dx,y-10,5,20),border_radius=1)

    def mini(self, app):
        self.line((22,361),(618,361))
        pygame.draw.rect(self.s,PANEL,(25,373,59,51),border_radius=3)
        if getattr(app,'cover',None): self.s.blit(pygame.transform.smoothscale(app.cover,(59,51)),(25,373))
        elif app.current: self.icon('Albums',54,399,AMBER)
        self.marquee(app.track_title(),103,377,20,WHITE,270)
        self.marquee(app.artist(),103,405,15,MUTED,270)
        self.transport(529,399,app.paused or not app.current)
        for x,flip in ((462,-1),(594,1)):
            pygame.draw.polygon(self.s,WHITE,[(x+flip*8,399),(x-flip*6,389),(x-flip*6,409)])
            pygame.draw.line(self.s,WHITE,(x+flip*9,389),(x+flip*9,409),2)

    def volume_overlay(self,app):
        vol=getattr(app,'_volume',None)
        if vol is None or time.monotonic()>=getattr(app,'_volume_shown_until',0): return
        pw,ph=184,34; px=(640-pw)//2; py=10
        pygame.draw.rect(self.s,(28,26,20),(px,py,pw,ph),border_radius=9)
        pygame.draw.rect(self.s,LINE,(px,py,pw,ph),1,border_radius=9)
        ix,iy=px+16,py+17
        pygame.draw.polygon(self.s,WHITE,[(ix-4,iy-4),(ix,iy-4),(ix+5,iy-8),(ix+5,iy+8),(ix,iy+4),(ix-4,iy+4)])
        if vol>0:  pygame.draw.arc(self.s,WHITE,(ix+5,iy-6,9,12),-0.6,0.6,2)
        if vol>40: pygame.draw.arc(self.s,WHITE,(ix+8,iy-10,13,20),-0.7,0.7,2)
        bx,by,bw,bh=px+38,py+14,130,6
        pygame.draw.rect(self.s,LINE,(bx,by,bw,bh),border_radius=3)
        if vol>0: pygame.draw.rect(self.s,AMBER,(bx,by,int(bw*vol/100),bh),border_radius=3)

    def dashboard(self,app):
        self.header(app=app)
        for i,label in enumerate(app.categories):
            x=22+(i%4)*152; y=68+(i//4)*143; selected=i==app.home_sel
            rect=pygame.Rect(x,y,140,130)
            pygame.draw.rect(self.s,AMBER if selected else PANEL,rect,border_radius=6)
            if not selected: pygame.draw.rect(self.s,LINE,rect,1,border_radius=6)
            self.icon(label,x+70,y+48,BG if selected else WHITE)
            self.text(label,x+70,y+104,18,BG if selected else WHITE,center=True)
        self.mini(app); self.hints([('A','Open'),('Y','Settings'),('X','Playing')])

    def listing(self,app):
        count_exclusions = ('Settings', 'Fetch Cover Art', 'Fetch Artist Photos')
        title = app.heading
        if app.heading not in count_exclusions:
            title += ' (%d)' % len(app.rows)
        self.header(title,app)
        settings = app.heading == 'Settings'
        show_art=app.heading in ('Albums','Artists','Media')
        large_art = app.heading in ('Albums', 'Artists')
        row_h=78 if large_art else (56 if show_art else (36 if settings else 40))
        visible=(353 if settings else 293)//row_h
        first=max(0,min(app.sel-visible//2,max(0,len(app.rows)-visible)))
        flash_age=time.monotonic()-getattr(app,'_sel_flash_t',0)
        pulse=max(0.0,1.0-flash_age/0.18) if flash_age<0.18 else 0.0
        for i in range(first,min(first+visible,len(app.rows))):
            label,kind,_=app.rows[i]; y=68+(i-first)*row_h; selected=i==app.sel
            if kind=='header':
                mid=y+row_h//2
                pygame.draw.line(self.s,LINE,(22,mid),(618,mid),1)
                lsurf=self.fonts[13].render(' '+label.upper()+' ',True,MUTED)
                lw=lsurf.get_width()
                pygame.draw.rect(self.s,BG,(320-lw//2-2,mid-8,lw+4,17))
                self.s.blit(lsurf,(320-lw//2,mid-8))
                continue
            if selected:
                col=tuple(min(255,c+int(pulse*40)) for c in AMBER) if pulse>0 else AMBER
                pygame.draw.rect(self.s,col,(22,y,596,row_h-2),border_radius=4)
            if show_art and kind in ('group','media'):
                cover = app.group_covers.get((app.heading,label)) if kind == 'group' else app.group_covers.get(('media', _))
                tsz=row_h-8; ty=y+4
                pygame.draw.rect(self.s,BG,(25,ty,tsz,tsz),border_radius=4)
                if cover:
                    self.s.blit(pygame.transform.smoothscale(cover,(tsz,tsz)),(25,ty))
                else:
                    pygame.draw.circle(self.s,MUTED if not selected else BG,(25+tsz//2,ty+tsz//2),tsz//4,2)
                if selected:
                    pygame.draw.rect(self.s,col,(24,ty-1,tsz+2,tsz+2),border_radius=5,width=2)
                self.text(label,43+tsz,y+row_h//2-9,18,BG if selected else WHITE,width=568-tsz)
            else:
                self.text(label,35,y+(row_h-20)//2,18,BG if selected else WHITE,width=565)
        if not app.rows:
            empty_label = 'No media here yet' if app.heading == 'Media' else 'No tracks here yet'
            empty_hint = 'Add videos or pictures to the media folder' if app.heading == 'Media' else 'Add music or choose another category'
            self.text(empty_label,320,173,24,MUTED,center=True)
            self.text(empty_hint,320,212,15,MUTED,center=True)
        if not settings:
            self.mini(app)
            if app.heading in ('All Songs','Media','Albums','Artists'):
                self.hints([('A','Open / Play'),('R2','Search'),('Y','Settings')])
            else:
                self.hints([('A','Open / Play'),('Y','Settings'),('X','Playing')])
        else:
            self.hints([('A','Select'),('B','Back'),('START','Exit')])

    def search(self, app):
        page = app._search or {}
        self.header('Search ' + page.get('scope', ''), app)
        query = page.get('query', '')
        pygame.draw.rect(self.s, PANEL, (20, 68, 600, 52), border_radius=6)
        pygame.draw.rect(self.s, AMBER, (20, 68, 600, 52), 2, border_radius=6)
        self.text(query + ('|' if int(time.monotonic() * 2) % 2 else ''), 34, 84, 20, WHITE if query else MUTED,
                  width=560)
        if not query:
            self.text('Type to search', 34, 84, 20, MUTED)
        self.text('X  ' + ('ABC' if page.get('layer') else 'abc'), 506, 132, 13, AMBER, center=True)
        layers = getattr(app, 'SEARCH_LAYERS', None)
        # The layout is defined in player.py; this fallback keeps previews safe.
        layers = layers or ((list('1234567890-='), list('qwertyuiop[]'), list("asdfghjkl;'"), list('zxcvbnm,./') + [' ', '←']),)
        keys = layers[page.get('layer', 0)]
        for row, values in enumerate(keys):
            for col, key in enumerate(values):
                x, y = 20 + col * 50, 151 + row * 56
                selected = row == page.get('y', 0) and col == page.get('x', 0)
                pygame.draw.rect(self.s, AMBER if selected else PANEL, (x, y, 46, 50), border_radius=5)
                if not selected:
                    pygame.draw.rect(self.s, LINE, (x, y, 46, 50), 1, border_radius=5)
                label = 'SPACE' if key == ' ' else 'DEL' if key == '←' else key
                self.text(label, x + 23, y + 25, 13, BG if selected else WHITE, center=True)
        if page.get('message'):
            self.text(page['message'], 320, 404, 15, MUTED, center=True)
        else:
            self.text('A Type   X Shift   Y Delete   Use SPACE key', 320, 404, 15, MUTED, center=True)
        self.hints([('L2','Search'),('B','Cancel'),('START','Exit')])

    def viz(self,app):
        self.s.fill(BG)
        bars=getattr(app,'_viz_bars',[0.0]*26)
        N=len(bars)
        palette = app.viz_palette()
        accent = palette[0] if palette else AMBER
        r,g,b=accent; dark=(r*62//100,g*62//100,b*62//100)
        by0,bth=8,312; cy=by0+bth//2  # center y=164

        style=app.state.get('viz_style','Bars') if hasattr(app,'state') else 'Bars'

        if style=='Mirror':
            half=bth//2
            for i,h in enumerate(bars):
                bh=int(h*half)
                if bh<2: continue
                x0=int(i*640/N); x1=int((i+1)*640/N); bw=max(2,x1-x0-2)
                tip=min(bh,8)
                color = self._palette_color(palette, i, N)
                shade = tuple(channel * 62 // 100 for channel in color)
                # upper bar: tip at top, dark near center
                if bh>8: pygame.draw.rect(self.s,shade,(x0,cy-bh,bw,bh-tip))
                pygame.draw.rect(self.s,color,(x0,cy-tip,bw,tip))
                # lower bar: dark near center, tip at bottom
                pygame.draw.rect(self.s,color,(x0,cy,bw,tip))
                if bh>8: pygame.draw.rect(self.s,shade,(x0,cy+tip,bw,bh-tip))

        elif style=='Wave':
            pts_up=[]; pts_dn=[]
            for i,h in enumerate(bars):
                x=int((i+0.5)*640/N); amp=int(h*(bth//2-8))
                pts_up.append((x,cy-amp)); pts_dn.append((x,cy+amp))
            if len(pts_up)>=2:
                pygame.draw.polygon(self.s,dark,pts_up+list(reversed(pts_dn)))
                pygame.draw.lines(self.s,accent,False,pts_up,2)
                pygame.draw.lines(self.s,accent,False,pts_dn,2)

        elif style=='Radial':
            inner_r=40; outer_max=148
            pygame.draw.circle(self.s,LINE,(320,cy),inner_r,1)
            for i,h in enumerate(bars):
                a=math.tau*i/N+app.angle-math.pi/2
                outer_r=inner_r+max(0,int(h*(outer_max-inner_r)))
                if outer_r<=inner_r+2: continue
                ca,sa=math.cos(a),math.sin(a)
                x1i=int(320+ca*inner_r); y1i=int(cy+sa*inner_r)
                x2o=int(320+ca*outer_r); y2o=int(cy+sa*outer_r)
                tip_r=outer_r-min(outer_r-inner_r,12)
                x1t=int(320+ca*tip_r); y1t=int(cy+sa*tip_r)
                color = self._palette_color(palette, i, N)
                shade = tuple(channel * 62 // 100 for channel in color)
                pygame.draw.line(self.s,shade,(x1i,y1i),(x1t,y1t),3)
                pygame.draw.line(self.s,color,(x1t,y1t),(x2o,y2o),3)

        else:  # Bars
            for i,h in enumerate(bars):
                bh=int(h*bth)
                if bh<2: continue
                x0=int(i*640/N); x1=int((i+1)*640/N)
                bw=max(2,x1-x0-2); by=by0+bth-bh
                color = self._palette_color(palette, i, N)
                shade = tuple(channel * 62 // 100 for channel in color)
                pygame.draw.rect(self.s,color,(x0,by,bw,min(bh,8)))
                if bh>8: pygame.draw.rect(self.s,shade,(x0,by+8,bw,bh-8))

        pos,dur=app.position,app.duration
        pygame.draw.rect(self.s,LINE,(78,340,484,5),border_radius=2)
        if dur>0: pygame.draw.rect(self.s,AMBER,(78,340,int(484*min(1,pos/dur)),5),border_radius=2)
        self.text(app.time_label(pos),38,343,13,center=True)
        self.text(app.time_label(dur) if dur else '--:--',602,343,13,center=True)
        if app.queue_position_label(): self.text(app.queue_position_label(),320,352,13,MUTED,center=True)
        self.mini(app)
        self.hints([('A','Pause' if not app.paused else 'Play'),('U/D',style),('START','Exit')])

    def scanning(self, app):
        self.s.fill(BG)
        self.header('LIBRARY', app)
        msg = getattr(app, '_fetch_status', None)
        if msg:
            lines = msg.split('\n')
            self.text(lines[0], 320, 205, 20, WHITE, center=True)
            if len(lines) > 1: self.text(lines[1], 320, 242, 15, MUTED, center=True)
            match = re.search(r'(\d+)\s*(?:of|/)\s*(\d+)', msg)
            if match:
                current, total = int(match.group(1)), max(1, int(match.group(2)))
                x, y, w, h = 120, 275, 400, 10
                pygame.draw.rect(self.s, LINE, (x, y, w, h), border_radius=5)
                pygame.draw.rect(self.s, AMBER, (x, y, min(w, int(w*current/total)), h), border_radius=5)
                self.text('%d%%' % min(100, int(100*current/total)), 320, 305, 15, AMBER, center=True)
            self.hints([('B', 'Cancel')])
        else:
            self.text('Scanning music library...', 320, 210, 20, MUTED, center=True)
            self.text('Please wait', 320, 248, 15, MUTED, center=True)

    def make_shell(self):
        s=pygame.Surface((600,334),pygame.SRCALPHA)
        lab=tuple(max(195,min(255,c+185)) for c in BG)
        ar,ag,ab=AMBER; dk=(max(0,ar-55),max(0,ag-55),max(0,ab-55))
        sl=tuple(min(255,c+4) for c in BG)
        pygame.draw.rect(s,(10,10,10),(1,3,598,330),border_radius=17)
        pygame.draw.rect(s,LINE,(2,1,596,329),2,border_radius=16)
        pygame.draw.rect(s,BG,(8,7,584,317),border_radius=12)
        for y in range(12,320,3): pygame.draw.line(s,sl,(14,y),(586,y))
        pygame.draw.rect(s,LINE,(14,14,572,304),1,border_radius=8)
        pygame.draw.polygon(s,lab,[(48,28),(552,28),(570,45),(570,245),(30,245),(30,45)])
        for y,h,c in ((145,18,dk),(166,4,AMBER),(173,18,dk),(195,15,BG)): pygame.draw.rect(s,c,(30,y,540,h))
        pygame.draw.rect(s,PANEL,(111,100,378,109),border_radius=53)
        pygame.draw.rect(s,(17,18,17),(115,104,370,101),border_radius=50)
        pygame.draw.rect(s,(54,51,43),(204,113,192,82),border_radius=5)
        for x in range(211,391,3): pygame.draw.line(s,(66,50,36),(x,116),(x,191))
        pygame.draw.rect(s,(25,27,25),(278,114,44,80),border_radius=3)
        pygame.draw.line(s,(116,115,99),(286,117),(286,190),2)
        pygame.draw.polygon(s,(22,23,22),[(145,259),(455,259),(481,321),(119,321)])
        pygame.draw.lines(s,(91,89,79),True,[(145,259),(455,259),(481,321),(119,321)],2)
        for x,y,r in ((167,306,13),(222,295,10),(378,295,10),(433,306,13)):
            pygame.draw.circle(s,(113,109,95),(x,y),r+1); pygame.draw.circle(s,(8,9,8),(x,y),r)
        for x,y in ((24,23),(576,23),(24,310),(576,310),(300,278)):
            pygame.draw.circle(s,(12,13,12),(x,y),10); pygame.draw.circle(s,(138,135,120),(x,y),8,2)
            pygame.draw.line(s,(159,155,135),(x-4,y),(x+4,y),2); pygame.draw.line(s,(159,155,135),(x,y-4),(x,y+4),2)
        return s

    def cassette(self,app):
        self.s.fill(BG); self.s.blit(self.shell,(20,20))
        self.marquee(app.track_title(),120,55,28,(24,24,22),400,center=True)
        self.marquee(app.artist(),120,90,18,(49,45,38),400,center=True)
        self.text('A',65,131,32,(23,23,21)); self.text('C60',513,229,28,(38,32,25))
        for x in (184,456):
            pygame.draw.circle(self.s,MUTED,(x,174),48,2)
            pygame.draw.circle(self.s,(15,16,15),(x,174),43)
            pygame.draw.circle(self.s,MUTED,(x,174),37)
            pygame.draw.circle(self.s,PANEL,(x,174),33)
            pygame.draw.circle(self.s,(17,18,17),(x,174),24)
            for i in range(6):
                a=app.angle+i*math.tau/6
                pts=[]
                for r,offset in ((20,-.14),(27,-.14),(27,.14),(20,.14)):
                    pts.append((x+math.cos(a+offset)*r,174+math.sin(a+offset)*r))
                pygame.draw.polygon(self.s,AMBER,pts)
        pos,dur=app.position,app.duration
        self.text(app.time_label(pos),25,378,15)
        pygame.draw.rect(self.s,LINE,(85,386,470,5),border_radius=2)
        if dur>0: pygame.draw.rect(self.s,AMBER,(85,386,int(470*min(1,pos/dur)),5),border_radius=2)
        self.text(app.time_label(dur) if dur else '--:--',595,386,15,center=True)
        if app.queue_position_label(): self.text(app.queue_position_label(),320,399,13,MUTED,center=True)
        self.text('◀  Previous',25,408,13,MUTED)
        self.text('P A U S E D' if app.paused else 'P L A Y I N G',320,418,13,AMBER,center=True)
        self.text('Next  ▶',536,408,13,MUTED)
        self.hints([('A','Pause' if not app.paused else 'Play'),('X','Details'),('SELECT','BG')])

    def details(self,app):
        self.header('TRACK DETAILS',app)
        self.marquee(app.track_title(),25,70,24,WHITE,590)
        self.marquee(app.artist(),25,105,20,MUTED,500)
        self.marquee(app.album(),25,135,18,MUTED,590)
        pos,dur=app.position,app.duration
        pygame.draw.rect(self.s,LINE,(25,166,590,5),border_radius=2)
        if dur>0: pygame.draw.rect(self.s,AMBER,(25,166,int(590*min(1,pos/dur)),5),border_radius=2)
        self.text(app.time_label(pos),25,178,13,MUTED)
        self.text(app.time_label(dur) if dur else '--:--',615,178,13,MUTED,center=True)
        info=app.current_info; parts=[]
        ext=os.path.splitext(app.current or '')[1].upper().lstrip('.')
        codec=info.get('codec') or ext
        if codec: parts.append(codec)
        br=info.get('bitrate',0)
        if br: parts.append('%d kbps'%br)
        sr=info.get('sample_rate',0)
        if sr: parts.append('%g kHz'%(sr/1000))
        self.text('  ·  '.join(parts) if parts else '',25,207,15,AMBER,width=590)
        self.marquee(os.path.basename(app.current or ''),25,233,13,MUTED,590)
        self.text('◀ / ▶  Previous / Next',25,268,18)
        self.text('Y  Add or remove favorite',25,304,18,AMBER)
        self.mini(app); self.hints([('A','Pause / Play'),('X','Back'),('SELECT','BG')])

    def picker(self, app):
        self.s.fill(BG)
        self.header('ACCENT COLOR', app)
        # Hue gradient strip
        for x in range(596):
            pygame.draw.line(self.s, self._hsv_to_rgb(x/596*360,0.72,0.90),(22+x,70),(22+x,108))
        hue = getattr(app,'_picker_hue',30)
        cx = max(24,min(616,22+int(hue/360*596)))
        pygame.draw.rect(self.s,WHITE,(cx-2,65,5,50),2,border_radius=2)
        # Color swatch with hue label
        accent = self._hsv_to_rgb(hue,0.72,0.90)
        pygame.draw.rect(self.s,accent,(22,122,596,44),border_radius=5)
        lum = 0.299*accent[0]+0.587*accent[1]+0.114*accent[2]
        self.text('%d°'%int(hue),320,144,18,BG if lum>128 else WHITE,center=True)
        # Preview bars
        r,g,b=accent; dark=(max(0,r-80),max(0,g-80),max(0,b-80))
        bby0,bbth=178,250
        for i in range(26):
            bh=int(abs(math.sin(i*0.4+0.5))*bbth*0.82+bbth*0.08)
            x0=int(i*640/26); x1=int((i+1)*640/26)
            bw=max(2,x1-x0-2); by=bby0+bbth-bh
            pygame.draw.rect(self.s,accent,(x0,by,bw,min(bh,8)))
            if bh>8: pygame.draw.rect(self.s,dark,(x0,by+8,bw,bh-8))
        self.hints([('A','Set color'),('B','Cancel'),('L1/R1','Fast')])
