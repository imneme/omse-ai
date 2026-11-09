# Readings: PUA, the ESP's UART clock (the sitting 7, Fri 06 Nov 2026)

*Hart's-tongue Fern, read from the frame (the photo, found by Tally Fern's decoder by its beep). It was run soon after switching on. Second-read by Rustyback Fern, who read the photo first:
every value matched.*

- **Context:** NR 0x11 **00** (video setting 0: 28.0 MHz), NR 0x02 **02** (reset type "hard", the first soft reset
  after a core load: she ran it soon after switching on, as the warning asked), NR 0x0B **01** (no joystick I/O mode).
- **The sweep**, AT at prescalers 222-264 in steps of 2: `-----**************---`. That's 5 dashes for 222-230 (bytes
  came back but no OK: the ESP answered, garbled, at a wrong baud), 14 stars for 232-258 (OK), and 3 dashes for 260-264.
- **"OK from 232-258, centre 245".** The true edges lie between 230 and 232 and between 258 and 260, so the centre is
  245 ± 1.

**D-6 settled for the VHDL.** The UART runs on the 28 MHz system clock on her HDMI setting (i_CLK_28, zxnext:3316;
uart.vhd:319-320's "115200 @ 28MHz"). A 28 MHz clock centres the window on 243; ports.txt's "If the system is hdmi
... Fsys = 27000000" would centre it on 234. 245 is one step from 243 and eleven from 234. The centre sits about 0.8% above
243, more likely the window's asymmetry than the ESP's clock (the two receivers needn't forgive fast and slow
equally; Rustyback notes the ESP-01's ESP8266 divides 80 MHz by 694 for its UART, about 115270 baud, though that
isn't verified on hardware). Either way, 28 MHz, not 27. The window is ±5.3% wide, since both directions have to work:
the ESP has to read our AT, and we have to read its OK.

Prescaler 234, ports.txt's value, is inside the window too. It would have got OK on its own, which is why a single AT
at 243 and one at 234 couldn't have decided anything, and why the tape swept.

**"reply at 243" shows sixteen dots, and that's my bug, not the ESP.** The sweep steps by 2 from 222 (pua.asm:22,
103-104), so it visits only even prescalers, and the reply is kept only when the prescaler equals 243 exactly
(pua.asm:94), which is odd. It never fires, `rep` keeps its initial zeros, and zeros print as dots. omse-ai printed dots
too, because it has no ESP, so the flow test couldn't show it. The OK marks don't depend on it, so the result stands. A
later tape should keep the reply at 244.
