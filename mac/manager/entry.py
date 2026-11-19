"""Frozen dispatch accepts only bundled workers; never execute a caller-supplied script."""
import pathlib
import runpy
import sys
if len(sys.argv) > 1 and sys.argv[1] == '--check-idle':
    import socket, json
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(3); sock.connect('/var/run/blewright/control.sock')
            sock.sendall(b'{"apiVersion":1,"action":"status"}\n')
            response = json.loads(sock.makefile('rb').readline(200000))
            if response.get('result', {}).get('busy'):
                raise SystemExit('BLEWright 正在操作固件，请完成后再安装更新')
    except FileNotFoundError: pass
    except ConnectionRefusedError: pass
elif len(sys.argv) > 1 and sys.argv[1] == '--esptool':
    import esptool
    esptool.main(sys.argv[2:])
elif len(sys.argv) > 1 and sys.argv[1].endswith('worker.py'):
    root = pathlib.Path(sys.executable).resolve().parents[1] / 'resources'
    allowed = [root/'mac/backends'/mode/'worker.py' for mode in ('esp32-scan','esp32-controlled')]
    script = pathlib.Path(sys.argv[1])
    if script not in allowed: raise SystemExit('Unknown worker')
    sys.argv = sys.argv[1:]
    sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name='__main__')
else:
    from manager import main
    main()
