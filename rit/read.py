import sys
import time

with open('response.data', 'rb') as f:
    data = f.read()

while 1:
    i,data = data[:4], data[4:]
    n = int(i, 16)-4
    msg,data = data[:n], data[n:]

    try:
        if msg[0] == 2:
            sys.stdout.write(msg[1:].decode())
        elif msg[0] == 1:
            with open('file.pack', 'ab') as f:
                f.write(msg[1:])
        time.sleep(0.02)
    except:
        exit()
