import time, serial
time.sleep(9)
with serial.Serial('/tmp/ttyV0', 115200) as p:
    p.write(b'\xA5\x5A\x00\x00\x00\x00\x03abc\x00\x00\x00\x00'); p.flush()
print("injected", time.time())
