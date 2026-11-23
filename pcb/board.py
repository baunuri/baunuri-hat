# The board's shape, shared by layout.py, preroute.py, route.py, stitch.py, silk.py and pathfind.py (mm from the top-left
# corner; KiCad's page has that corner at X0, Y0). POPM-HAT: Raspberry Pi HAT size, the Pi's hole pattern.
X0, Y0 = 100.0, 100.0
W, H = 65.0, 57.0
CORNER_R = 3.0                            # the HAT spec's corner radius
HOLES = [(3.5, 4.0), (61.5, 4.0), (3.5, 53.0), (61.5, 53.0)]   # 58 x 49 mm, 3 mm NPTH (M2.5)
HEAD_R = 3.0                              # screw head / standoff keep-out round each hole, both sides
MODULE = (12.25, 20.0)                    # the ESP32-S3 module (rotated 90: antenna to the left): body x 0..25.5, y 11..29
NOTCH = (5.0, 11.5, 28.5)                 # x depth, y from / to: board cut away under the antenna (Espressif)
ANT = (0.0, 8.0, 6.0, 32.0)               # the antenna keep-out (all copper layers): the left strip beside the antenna
