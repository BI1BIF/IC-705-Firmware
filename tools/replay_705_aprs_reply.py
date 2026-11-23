"""Replay the installed four-mode QUICK list, message keyboard, alert choices and RF modulation."""
from struct import pack, unpack
from tools.emulate_705 import call
from tools.replay_705_aprs_beacon import ATEST, FM_HZ, INIT_RANGES, SELECT_VFO, seed_vfos
from tools.replay_705_aprs_fm import GUARD, RATE, write_wav
from tools.replay_705_aprs_rx import dire_wolf
from tools.replay_705_dv_panel import attach_position_graphics
from tools.replay_705_settings import UPDATE
from tools.verify_705_aprs_overlay import LINK


def exercise(guest,folder,base,sy,ms,gps,tones,*,timer_baseline=False,ptt_baseline=False,default_comment=False):
    cpu,rom=guest.cpu,guest.rom
    out=folder/("default-comment" if default_comment else "messages")
    out.mkdir(exist_ok=True)
    attach_position_graphics(guest)
    def sym(name): return base+sy[name]-LINK
    def u(a,n=4): return int.from_bytes(cpu.mem_read(a,n),"little")
    def screen(name,*labels):
        words,png=guest.render()
        (out/(name+".png")).write_bytes(png)
        assert set(labels)<=set(words),(name,words)
        return words
    def tap(row): guest.click(150,55+61*row)
    def panel(): call(cpu,sym("aprs_update_panel"),timeout_us=0)
    def receive(info,source="N0MSG-2",via=b""):
        # This fixture supplies a validated AX.25 UI frame at the modem output;
        # the preceding panel test feeds clean and corrupt waveforms at the DMA entry.
        def address(call,last):
            base,_,ssid=call.partition("-")
            return bytes(ord(c)<<1 for c in base.ljust(6))+bytes([0x60+2*int(ssid or 0)+last])
        frame=address("APRS",0)+address(source,not via)+via+b"\x03\xf0"+info.encode()+bytes(2)
        seq=u(sym("aprs_rx_written"))
        ptr=sym("aprs_rx_frames")+340*(seq%4)
        cpu.mem_write(ptr,pack("<II",0,len(frame))+frame)
        cpu.mem_write(sym("aprs_rx_written"),pack("<I",seq+1))
        call(cpu,ms["aprs_slot_drain"])
        panel()
    from tools.verify_705_ftx_tx import mount_station_card
    from tools.verify_705_ftx_rx import symbols
    from tools.build_705_ftx_rx import OUT as FT_OUT
    from tools.replay_705_aprs_beacon import EDITOR_TEXT
    cardnames=[rf"C:\IC-705\APRS{i}.CFG" for i in range(2)]
    card,_,_=mount_station_card(cpu,symbols(FT_OUT/"rx.elf"),rom,extra_paths=cardnames+[k.replace("APRS","APRT") for k in cardnames])
    def prepare():
        call(cpu,ms["aprs_overlay_prepare"],instruction_limit=4000000,timeout_us=0)
    def advance(ms):
        cpu.mem_write(0x20381e08,pack("<I",(u(0x20381e08)+ms)&0xffffffff))
        panel()
    gps()
    guest.click(150,240)
    guest.render()
    tap(1)
    guest.render()
    guest.press_exit()
    guest.render()
    tap(2)
    screen("01-aprs","RX Alert")
    tap(1)
    screen("01b-ssid","Beacon SSID","0","1","2","3")
    tap(3)
    screen("01c-ssid-chosen","Beacon SSID  3","RX Alert")
    tap(2);screen("01d-auto","Auto Beacon","OFF","ON")
    tap(1);screen("01e-auto-set","Auto Beacon  ON")
    tap(3);screen("01f-interval","Beacon Interval","1 min")
    if default_comment:
        for _ in range(2):
            call(cpu,rom(0x200cd168),1,1)
            guest.render()
        screen("01f-smart","SmartBeaconing")
        guest._press_key(0,1)
        screen("01f-smart-set","Beacon Interval  Smart")
        prepare()
        assert any(card[path][16]==5 for path in cardnames if path in card)
        for path in cardnames:
            (out/path.rsplit("\\",1)[-1]).write_bytes(card[path])
        tap(3);guest.render();guest.click(395,65);guest.render()
    tap(0);screen("01g-interval-set","Beacon Interval  1 min")
    prepare()
    assert any(card.get(k) for k in cardnames)
    guest.click(395,160);guest.render()
    tap(0);screen("01h-path","TX Path","Direct")
    tap(1);screen("01i-path-set","TX Path  WIDE2-1")
    tap(1);screen("01j-symbol","Beacon Symbol","Primary Symbols")
    tap(0);labels=screen("01k-symbol-list","Primary Symbols")
    tap(0);screen("01l-symbol-set","Beacon Symbol")
    tap(2);call(cpu,rom(UPDATE),instruction_limit=2000000)
    assert guest.state()["menu"]==349
    if default_comment:
        from tools.replay_705_aprs_beacon import DEFAULT_COMMENT
        assert bytes(cpu.mem_read(EDITOR_TEXT,43)).rstrip(b" ")==DEFAULT_COMMENT.encode()
        guest.press_exit()
        call(cpu,rom(UPDATE),instruction_limit=2000000)
        if guest.state()["menu"]==349:
            guest.click(229,193)
    else:
        cpu.mem_write(EDITOR_TEXT,b"Field test".ljust(43,b" "))
        guest.click(443,194)
    screen("01m-comment-set","Beacon Comment")
    prepare()
    if default_comment:
        assert not u(sym("comment_saved"),1)
    else:
        assert all(path in card for path in cardnames) and bytes(cpu.mem_read(sym("saved_comment"),11))==b"Field test\0"
        for path in cardnames:
            (folder/path.rsplit("\\",1)[-1]).write_bytes(card[path])
    # Put Direct and manual timing back for the original RF fixtures.
    tap(0);guest.render();tap(0);guest.render()
    guest.click(395,65);guest.render();tap(2);guest.render();tap(0);guest.render()
    tap(0)
    screen("02-alert-events","RX Alert","Position Beacon","Weather","My Beacon Relayed","Message to Me")
    tap(1)
    screen("03-weather-tones","Weather","List Only","Silent Popup","Short Tone","Double Short")
    assert not call(cpu,ms["aprs_overlay_unload"])
    tones.clear()
    tap(3)
    screen("04-selected","RX Alert")
    assert u(sym("aprs_alert_styles")+1,1)==3 and 3 in tones,tones
    for _ in range(5):
        guest.press_exit()
        guest.render()
        if guest.state()["menu"]==0 and not u(0x203e1a28,2):
            break
    seed_vfos(cpu,(FM_HZ,145000000))
    call(cpu,rom(INIT_RANGES))
    call(cpu,rom(SELECT_VFO[0]))
    from tools.probe_705_cw_menu import MODE_VFO_A,MODE_UI_A
    for a in (MODE_VFO_A,MODE_UI_A,0x203e2128,0x203e212f,0x203e2136): cpu.mem_write(a,b"\x70\x00")
    cpu.mem_write(0x203e2499,b"N0HOME  ")
    cpu.mem_write(0x203eaa7d,b"\x01")
    cpu.mem_write(0x203eaac8,bytes(2))
    cpu.mem_write(0x2038087c,pack("<5I",65536,43690,32768,21845,10922))
    tones.clear()
    receive(":N0HOME-3 :MEET AT NOON{12")
    screen("05-message","APRS MESSAGE","MEET AT NOON","N0MSG-2","Reply")
    assert 8 in tones and u(0x203871a4+8,1)==50,tones
    cpu.mem_write(0x20381e08,pack("<I",u(0x20381e08)+180))
    panel()
    assert 5 in tones and u(0x203871a4+8,1)==63,tones
    # Advance the OEM beep sequencer between independent simulated gestures.
    call(cpu,rom(0x2000e73c),0)
    call(cpu,rom(0x2000e73c),1)
    cpu.mem_write(0x203eaa7d,b"\x00")
    guest.press_exit()
    panel()
    assert not u(0x203807dd,2),(guest.state(),u(0x203807dd,2),u(0x20392fe0,2),tones)
    tones.clear()
    receive(":N0HOME-3 :MEET AT NOON{12")
    assert not u(0x203807dd,2) and not any(tones),(u(0x203807dd,2),tones)
    guest._press_key(1,1)
    screen("06-quick","QUICK MENU","APRS RX List","Send APRS Beacon")
    tap(0)
    assert u(0x203e1a28,2)==170
    screen("07-list","APRS RX List","N0MSG-2")
    tap(0)
    screen("08-detail","APRS MESSAGE","Reply")
    guest.press_exit()
    panel()
    screen("09-back","APRS RX List")
    guest.press_exit()
    panel()
    assert not u(0x203e1a28,2)
    guest._press_key(1,1)
    guest.render()
    tap(0)
    guest.render()
    tap(0)
    guest.render()
    guest.click(280,240)
    call(cpu,rom(UPDATE),instruction_limit=2000000)
    assert guest.state()["menu"]==349 and not call(cpu,ms["aprs_overlay_unload"]),guest.state()
    guest.click(210,90)
    guest.press_exit()
    call(cpu,rom(UPDATE),instruction_limit=2000000)
    assert guest.click(229,193)==0x22f
    screen("09b-canceled","APRS RX List")
    assert u(sym("stage"))==0 and u(0x203e1a28,2)==170
    tap(0)
    guest.render()
    guest.click(280,240)
    call(cpu,rom(UPDATE),instruction_limit=2000000)
    guest.click(210,90)
    guest.click(443,194)
    screen("10-review","APRS Reply","To  N0MSG-2","Send")
    assert u(sym("stage"))==0
    tap(2)
    screen("11-queued","Reply queued")
    assert u(sym("stage"))==1
    def transmit(wav, *, during_tx=None):
        assert call(cpu,ms["aprs_slot_request"],0)&32
        cpu.mem_write(0x203809a1,bytes([u(0x203809a1,1)|16]))
        if during_tx:
            during_tx()
        pcm=[]
        for _ in range(2000):
            assert call(cpu,ms["aprs_slot_mod"],timeout_us=0)==4
            pcm.extend(unpack("<36h",cpu.mem_read(0x20401c14,72)))
            if u(sym("stage"))==4:break
        assert u(sym("stage"))==4
        cpu.mem_write(0x203809a1,bytes([u(0x203809a1,1)&~16]))
        call(cpu,ms["aprs_slot_request"],0)
        write_wav(out/wav,GUARD+tuple(pcm)+GUARD,RATE)
        return dire_wolf(ATEST.resolve(),out.resolve(),wav,out)
    decoded=transmit("reply.wav")
    assert [x["text"] for x in decoded]==["N0HOME-3>APRS::N0MSG-2  :A{001"],decoded
    guest.press_exit()
    panel()
    if u(0x203e1a28,2):
        guest.press_exit()
        panel()
    advance(1600)
    assert transmit("auto-ack.wav")[0]["text"].endswith("::N0MSG-2  :ack12")
    receive(":N0HOME-3 :MEET AT NOON{12")
    assert not u(0x203807dd,2)
    advance(1600)
    assert transmit("duplicate-ack.wav")[0]["text"].endswith("::N0MSG-2  :ack12")
    advance(30000)
    assert transmit("retry.wav")[0]["text"]==decoded[0]["text"]
    tones.clear()
    receive(":N0HOME-3 :ack001","N0WRNG")
    assert not u(0x203807dd,2) and not any(tones)
    receive(":N0HOME-3 :ack001")
    screen("12-ack","MESSAGE ACK","ack001")
    assert 8 in tones
    guest.press_exit()
    panel()
    tones.clear()
    receive(":N0HOME-3 :ack001")
    assert not u(0x203807dd,2) and not any(tones)
    receive(">Ready")
    assert not u(0x203807dd,2)
    receive("_11220001c090s005g010t040")
    screen("13-weather","WEATHER REPORT")
    assert 3 in tones
    guest.press_exit()
    panel()
    # A different SSID at the same callsign is another station.
    tones.clear()
    receive(":N0HOME-1 :WRONG SSID{2")
    assert not u(0x203807dd,2) and not any(tones)
    # Exercise a real second outbound burst before feeding back the same
    # information with changed AX.25 path/H bits.
    guest._press_key(1,1)
    screen("14-quick-beacon","Send APRS Beacon")
    tap(1)
    assert u(sym("stage"))==1
    beacon=transmit("beacon.wav")[0]["text"]
    if default_comment:
        assert beacon.endswith(DEFAULT_COMMENT) and not u(sym("comment_saved"),1),beacon
        cpu.mem_write(sym("aprs_auto_beacon"),bytes([1]))
        advance(60000)
        timed=transmit("timed-default.wav")
        assert [p["text"] for p in timed]==[beacon]
        # Use the region's real VFO commit and the installed manager for off-channel timing.
        here=0x20380714
        source=FM_HZ+25000
        def tune(hz):
            assert call(cpu,sym("tune_vfo"),hz) and u(here)==hz
        def poll(delta):
            clock=0x20381e08
            cpu.mem_write(clock,pack("<I",(u(clock)+delta)&0xffffffff))
            prepare()
            call(cpu,ms["aprs_slot_update"])
        tune(source)
        other=bytes(cpu.mem_read(0x203ebc2e+37,36))
        poll(59999)
        assert u(here)==source and not u(sym("stage")) and u(ms["loaded"])==base
        cpu.mem_write(0x2038026c,b"\x01");poll(1)
        assert u(here)==source and not u(sym("stage"))
        cpu.mem_write(0x2038026c,bytes(1));poll(1000)
        assert u(here)==FM_HZ and not u(sym("stage"))
        poll(399);assert not u(sym("stage"))
        poll(1);assert u(sym("stage"))==1 and u(here)==FM_HZ
        def still_on_aprs():
            poll(20)
            assert u(here)==FM_HZ and u(sym("aprs_return_hz"))==source
        hop=transmit("off-channel.wav",during_tx=still_on_aprs)
        assert [p["text"] for p in hop]==[beacon]
        poll(1);assert u(here)==source and not u(sym("aprs_return_hz"))
        poll(60000);assert u(here)==FM_HZ
        cpu.mem_write(0x2038026c,b"\x01");poll(400)
        assert u(here)==source and not u(sym("stage"))
        cpu.mem_write(0x2038026c,bytes(1));poll(60000)
        assert u(here)==FM_HZ
        tune(source+5000);poll(400)
        assert u(here)==source+5000 and not u(sym("stage")) and not u(sym("aprs_return_hz"))
        cpu.mem_write(symbols(FT_OUT/"rx.elf")["state"],pack("<I",2));poll(120000)
        assert not u(ms["loaded"]) and u(here)==source+5000
        cpu.mem_write(symbols(FT_OUT/"rx.elf")["state"],bytes(4));poll(1)
        base=u(ms["loaded"])
        assert base and u(here)==source+5000 and not u(sym("stage"))
        poll(59999);assert u(here)==source+5000
        poll(1);assert u(here)==FM_HZ
        assert bytes(cpu.mem_read(0x203ebc2e+37,36))==other
        cpu.mem_write(0x2038026c,b"\x01");poll(400)
        cpu.mem_write(0x2038026c,bytes(1))
        # Select an FM VFO B, then visit the VHF beacon channel from UHF.
        vfo=0x203ebc2e
        cpu.mem_write(vfo+37+4,b"\x70\0")
        cpu.mem_write(vfo+115+4,b"\x70\0")
        call(cpu,rom(SELECT_VFO[0])+20)
        assert u(vfo+74,1)&4
        tune(433500000);poll(1)
        before_a=bytes(cpu.mem_read(vfo+37,36))
        poll(60000);assert u(here)==FM_HZ and u(vfo+74,1)&4
        poll(400)
        assert [p["text"] for p in transmit("off-channel-vfo-b.wav")]==[beacon]
        poll(1)
        assert u(here)==433500000 and u(vfo+74,1)&4 and bytes(cpu.mem_read(vfo+37,36))==before_a
        from tools.replay_705_gps_inputs import BYTE_RX, GPS_MODE, POSITION_AGE, nmea
        tune(FM_HZ)
        cpu.mem_write(sym("aprs_beacon_interval"),bytes([5]))
        call(cpu,sym("aprs_beacon_reschedule"))
        cpu.mem_write(GPS_MODE,bytes([1]))
        # Feed real GPS sentences with empty speed and course. Motion must come
        # from this radio's successive fixes, even with no motion fields.
        def fix(north,east):
            line=f"GPRMC,120000.00,A,35{30+north:.4f},N,139{30+east:.4f},E,,,141126,,,A"
            for byte in nmea(line):
                call(cpu,rom(BYTE_RX),byte)
        fix(0,0);poll(0)
        for n in range(1,13):
            fix(n*.12,0);poll(10000)
            assert u(sym("stage"))==int(n==12),("straight",n,u(sym("stage")))
        straight=transmit("smart-straight.wav")[0]["text"]
        assert "3531.44N" in straight and straight.endswith(DEFAULT_COMMENT)
        # Turn east. Carrier busy at the corner deadline, clear a second later.
        for n in range(1,7):
            if n==6: cpu.mem_write(0x2038026c,b"\x01")
            fix(1.44,n*.15);poll(10000)
            assert not u(sym("stage")),("turn",n)
        cpu.mem_write(0x2038026c,bytes(1));poll(1000)
        corner=transmit("smart-turn.wav")[0]["text"]
        assert "13930.90E" in corner
        cpu.mem_write(POSITION_AGE,b"\x73")
        tune(source);poll(1800000);poll(1000)
        assert u(here)==source and not u(sym("stage"))
        cpu.mem_write(GPS_MODE,bytes(1));poll(1800000)
        assert u(here)==source and not u(sym("stage"))
        tune(FM_HZ);cpu.mem_write(GPS_MODE,bytes([2]))
        call(cpu,sym("aprs_beacon_reschedule"))
        poll(1799999);assert not u(sym("stage"))
        poll(1);manual_position=transmit("smart-static.wav")[0]["text"]
        assert manual_position==beacon
        cpu.mem_write(GPS_MODE,bytes([1]))
        call(cpu,sym("aprs_beacon_reschedule"))
        fix(0,0);poll(0)
        for n in range(1,35):
            # About 30 km/h. Cross north after transmitting at 280 seconds.
            east=.001*n if n<=28 else .001*(56-n)
            fix(n*.045,east);poll(10000)
            assert u(sym("stage"))==int(n==28),("middle speed / north crossing",n)
            if n==28:
                middle=transmit("smart-middle.wav")[0]["text"]
                assert "3531.26N" in middle
        cpu.mem_write(symbols(FT_OUT/"rx.elf")["state"],pack("<I",2))
        poll(1800000)
        assert not u(ms["loaded"]) and u(here)==FM_HZ
        return dict(editor=DEFAULT_COMMENT,manual=beacon,timed=timed[0]["text"],off_channel=hop[0]["text"],
                    smart=dict(straight_120s=straight,turn_60s_then_busy_1s=corner,
                               middle_280s=middle,north_crossing_quiet=True,ft_unloaded=True,
                               manual_30min=manual_position,stale_and_off_no_excursion=True,sd_choice=5),
                    returned_to=source,source_and_target_busy_deferred=True,user_retune_preserved=True,
                    ft_unloaded_and_restarted_full_interval=True,vfo_b_returned_to=433500000)
    info=beacon.split(":",1)[1]
    relay=bytes(ord(c)<<1 for c in "N0DIGI")+bytes([0xe1])
    unused=relay[:-1]+bytes([0x61])
    receive(info,"N0HOME-3",unused)
    screen("15-unused-hop","POSITION BEACON")
    guest.press_exit()
    panel()
    tones.clear()
    receive(info,"N0HOME-3",relay)
    screen("16-relayed","MY BEACON RELAYED")
    assert 3 in tones
    guest.press_exit()
    panel()
    tones.clear()
    receive(info,"N0HOME-3",relay)
    assert not u(0x203807dd,2) and not any(tones)
    guest._press_key(1,1);screen("17a-msg-quick","APRS Messages");tap(2)
    screen("17b-msg-menu","New Message","Inbox","Outbox")
    tap(0);call(cpu,rom(UPDATE),instruction_limit=2000000)
    assert guest.state()["menu"]==349
    cpu.mem_write(EDITOR_TEXT,b"N0NEW-4  ")
    guest.click(443,194)
    call(cpu,rom(UPDATE),instruction_limit=2000000)
    assert guest.state()["menu"]==349
    guest.click(210,90);guest.click(443,194)
    screen("17c-new-review","To  N0NEW-4","Send")
    tap(2);screen("17d-new-sent","Message queued")
    assert transmit("new.wav")[0]["text"].endswith("::N0NEW-4  :A{002")
    guest.press_exit();screen("17e-outbox","Outbox","N0NEW-4  Awaiting ACK","N0MSG-2  Delivered")
    tap(0);screen("17f-sent-detail","Cancel retries","002")
    tap(3);screen("17g-canceled","N0NEW-4  Canceled")
    guest.press_exit();screen("17h-msg-back","Inbox")
    tap(1);screen("17i-inbox","Inbox","N0MSG-2")
    tap(0);screen("17j-inbox-actions","Read","Mark Unread");tap(1);screen("17k-unread","Inbox","*")
    tap(0);guest.render();tap(0);screen("17l-inbox-detail","APRS MESSAGE","MEET AT NOON")
    guest.press_exit();panel();assert "*" not in screen("17m-read","Inbox","N0MSG-2")
    guest.press_exit();screen("17n-message-tools-entry","Message Tools");tap(3)
    screen("17o-message-tools","Edit Quick Text","Auto Reply","New from Quick Text")
    def keyboard(value,width):
        call(cpu,rom(UPDATE),instruction_limit=2000000)
        assert guest.state()["menu"]==349,guest.state()
        cpu.mem_write(EDITOR_TEXT,value.encode().ljust(width,b" "))
        guest.click(443,194)
    tap(0);guest.render();tap(1);guest.render();tap(0);keyboard("QRV",32)
    screen("17p-saved-phrase","QRV")
    assert any("APRT" in name for name in card)
    guest.press_exit();guest.render();guest.press_exit();guest.render()
    tap(2);guest.render();tap(1);guest.render();tap(0);keyboard("N0AUTO-7",9)
    screen("17q-phrase-review","To  N0AUTO-7","QRV","Send");tap(2);guest.render()
    assert transmit("phrase.wav")[0]["text"].endswith("::N0AUTO-7 :QRV{003")
    guest.press_exit();guest.render();guest.press_exit();guest.render();tap(3);guest.render()
    tap(1);screen("17r-answer-settings","Auto Reply","Reply Text")
    tap(1);keyboard("QRX",64);guest.render();tap(2);keyboard("N0AUTO-7",9);guest.render()
    tap(3);guest.render();tap(0);guest.render();tap(0);guest.render();tap(1)
    screen("17s-answer-on","Auto Reply  ON","Reply To  N0AUTO-7")
    for _ in range(5):
        guest.press_exit();guest.render()
        if not u(0x203e1a28,2):break
    receive(":N0HOME-3 :rej003","N0AUTO-7")
    screen("17t-rejected","rej003");guest.press_exit();panel()
    receive(":N0HOME-3 :QRV?{ABC","N0AUTO-7");guest.press_exit();panel()
    advance(1600);assert transmit("answer-ack.wav")[0]["text"].endswith("::N0AUTO-7 :ackABC")
    advance(1);assert transmit("auto-answer.wav")[0]["text"].endswith("::N0AUTO-7 :AA:QRX{004")
    for attempt in range(4):
        advance(30000)
        assert transmit(f"limited-{attempt}.wav")[0]["text"].endswith("::N0AUTO-7 :AA:QRX{004")
    advance(30000);assert not u(sym("stage"))
    guest._press_key(1,1);guest.render();tap(2);guest.render();tap(2)
    screen("17u-timeout","N0AUTO-7  Timed out","N0AUTO-7  Rejected")
    guest.press_exit();guest.render();guest.press_exit();panel()
    receive("}N0USER-5>APRS,TCPIP,N0GAT*::N0HOME-3 :GATED MESSAGE{G7","N0GAT")
    screen("17v-gated-message","N0USER-5","GATED MESSAGE","Reply")
    guest.press_exit();panel();advance(1600)
    gated_ack=transmit("gated-ack.wav")[0]["text"]
    assert gated_ack.endswith("::N0USER-5 :ackG7"),gated_ack
    from tools.build_705_ftx_rx import OUT as FT_OUT
    from tools.verify_705_ftx_rx import symbols
    ft=symbols(FT_OUT/"rx.elf")
    cpu.mem_write(sym("aprs_auto_beacon"),bytes([1]))
    cpu.mem_write(sym("aprs_beacon_interval"),bytes([0]))
    call(cpu,sym("aprs_beacon_reschedule"))
    # Exercise the installed manager callback on both sides of the minute boundary.
    from tools.probe_705_rx_audio import AUDIO_GATE
    def timer_tick(delta):
        clock=0x20381e08
        cpu.mem_write(clock,pack("<I",(u(clock)+delta)&0xffffffff))
        call(cpu,ms["aprs_slot_update"])
        return u(sym("stage"))
    assert timer_tick(59999)==0
    cpu.mem_write(AUDIO_GATE,b"\x01")
    assert timer_tick(1)==0
    assert timer_tick(2000)==0
    cpu.mem_write(AUDIO_GATE,b"\x00")
    if timer_baseline:
        assert timer_tick(1000)==0
        return dict(missed_when_channel_cleared=True,interval_ms=60000)
    assert timer_tick(1000)==1
    def verify_timed_burst(name):
        packets=transmit(name+".wav")
        assert [p["text"] for p in packets]==[beacon],packets
    verify_timed_burst("timer-after-busy")
    assert timer_tick(59999)==0 and timer_tick(1)==1
    verify_timed_burst("timer-next-minute")
    guest._press_key(1,1)
    guest.render()
    assert timer_tick(120000)==0
    guest.press_exit()
    assert timer_tick(1000)==1
    verify_timed_burst("timer-after-menu")
    assert timer_tick(1000)==0
    # The raw mic input can stay asserted while the original PTT filter reports RX.
    from tools.replay_705_ptt_tune import PORT_PTT, PTT_PASSES, PANEL_PTT
    from tools.probe_705_cw_pcm import simulated_gpio
    simulated_gpio(cpu,rom=rom)
    cpu.mem_write(PORT_PTT,bytes(2))
    call(cpu,rom(PTT_PASSES[0]))
    assert u(PANEL_PTT,1)&1 and not u(AUDIO_GATE,1) and not u(0x203809b0)
    assert not u(0x203806f4,1)&0xa0 and not u(0x203809a1,1)&16
    if ptt_baseline:
        for delta in (60000,1000,60000):
            assert timer_tick(delta)==0 and u(sym("auto_waiting"))
        assert not call(cpu,sym("aprs_beacon_start")) and u(sym("stage"))==1
        verify_timed_burst("manual-while-timer-blocked")
        return dict(raw_mic_sample=1,filtered_requests=0,channel_busy=0,wait_reproduced=True,manual_decoded=beacon)
    assert timer_tick(60000)==1 and not u(sym("auto_waiting"))
    verify_timed_burst("timer-raw-mic")
    cpu.mem_write(0x203809b0,pack("<I",0x200))
    assert timer_tick(60000)==0 and timer_tick(1000)==0 and u(sym("auto_waiting"))
    cpu.mem_write(0x203809b0,bytes(4))
    assert timer_tick(1000)==1 and not u(sym("auto_waiting"))
    verify_timed_burst("timer-after-mic-release")
    cpu.mem_write(PORT_PTT,pack("<H",0x2000))
    call(cpu,rom(PTT_PASSES[0]))
    assert not u(PANEL_PTT,1)&1
    call(cpu,sym("aprs_beacon_reschedule"))
    receive(":N0HOME-3 :NO TX IN FT{FT","N0FT");guest.press_exit();panel()
    cpu.mem_write(ft["state"],pack("<I",2))
    count=u(sym("aprs_record_count"))
    for ft4 in (0,1):
        cpu.mem_write(ft["ftx_ft4"],pack("<I",ft4))
        tones.clear()
        receive(":N0HOME-3 :DURING FT{99","N0FT")
        assert u(sym("aprs_record_count"))==count and not u(0x203807dd,2) and not any(tones)
    cpu.mem_write(0x20381e08,pack("<I",(u(0x20381e08)+60000)&0xffffffff))
    panel()
    assert not u(sym("stage")) and not call(cpu,sym("aprs_active_frequency"))
    cpu.mem_write(ft["state"],bytes(4))
    panel()
    assert not u(sym("stage"))
    cpu.mem_write(sym("aprs_auto_beacon"),bytes(1))
    gps()
    guest.click(150,240)
    guest.render()
    tap(0)
    guest.render()
    for _ in range(3):
        guest.press_exit()
        guest.render()
    receive(":N0HOME-3 :RX ONLY TEST{13")
    assert "Reply" not in screen("17-rx-only","APRS MESSAGE","RX ONLY TEST")
    guest.press_exit()
    panel()
    guest._press_key(1,1)
    advance(2000);assert not u(sym("stage"))
    assert "Send APRS Beacon" not in screen("18-rx-quick","QUICK MENU","APRS RX List")
    guest.press_exit()
    panel()
    cpu.mem_write(ft["state"],pack("<I",2))
    call(cpu,ms["aprs_overlay_prepare"],instruction_limit=4000000,timeout_us=0)
    assert not u(ms["loaded"])
    cpu.mem_write(ft["state"],bytes(4))
    call(cpu,ms["aprs_overlay_prepare"],instruction_limit=4000000,timeout_us=0)
    base=u(ms["loaded"])
    assert base and u(sym("aprs_beacon_ssid"),1)==3 and u(sym("aprs_alert_styles")+1,1)==3
    return dict(timed_beacons=["timer-after-busy","timer-next-minute","timer-after-menu","timer-raw-mic","timer-after-mic-release"],gated_ack=gated_ack,inbox_read_unread=True,quick_text_slot_11=True,filtered_auto_answer=True,rejected_and_five_attempt_timeout=True,ft_suppressed_pending_ack=True,new_message=True,retry_same_id=True,duplicate_ack=True,outbox_cancel=True,settings_written=True,decoded=decoded[0]["text"],weather_preview=3,message_pattern=[8,5],duplicate_silent=True,
                own_relay_once=True,matched_ack_once=True,wrong_sender_and_ssid_silent=True,ft_suppressed_due_beacon=True,rx_only_read_only=True,settings_survived_ft_reload=True,nonzero_ssid=True,cancel_did_not_transmit=True,native_keyboard=True,send_required=True,history_exit=True)
