#!/usr/bin/env python3
"""
NOMAD Monitor - GPU/CPU/Ollama dashboard
Run: sudo python3 nomad_monitor.py
Then open http://YOUR_IP:7070 in a browser
"""
import subprocess
import json
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen
from urllib.error import URLError

OLLAMA_API = "http://localhost:11434"
PORT = 7070

def detect_gpu():
    # Returns 'nvidia', 'amd', or None
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=3)
        if r.returncode == 0:
            return "nvidia"
    except Exception:
        pass
    try:
        r = subprocess.run(["rocm-smi"], capture_output=True, timeout=3)
        if r.returncode == 0:
            return "amd"
    except Exception:
        pass
    return None

GPU_TYPE = detect_gpu()

def get_gpu_stats_nvidia():
    try:
        result = subprocess.run([
            "nvidia-smi",
            "--query-gpu=name,temperature.gpu,utilization.gpu,utilization.memory,"
            "memory.used,memory.total,power.draw,power.limit,clocks.sm,clocks.mem",
            "--format=csv,noheader,nounits"
        ], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return {"error": "nvidia-smi failed"}
        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) < 10:
            return {"error": "unexpected output"}
        return {
            "name": parts[0],
            "temp": float(parts[1]),
            "gpu_util": float(parts[2]),
            "mem_util": float(parts[3]),
            "mem_used": float(parts[4]),
            "mem_total": float(parts[5]),
            "power_draw": float(parts[6]),
            "power_limit": float(parts[7]),
            "clock_sm": float(parts[8]),
            "clock_mem": float(parts[9]),
            "vendor": "nvidia",
        }
    except Exception as e:
        return {"error": str(e)}

def get_gpu_stats_amd():
    try:
        # Get GPU name
        name_result = subprocess.run(
            ["rocm-smi", "--showproductname", "--csv"],
            capture_output=True, text=True, timeout=5
        )
        name = "AMD GPU"
        for line in name_result.stdout.splitlines():
            if line.startswith("card") or (line and not line.startswith("device")):
                parts = line.split(",")
                if len(parts) >= 2:
                    name = parts[1].strip()
                    break

        # Get all stats in one call
        result = subprocess.run(
            ["rocm-smi", "--showtemp", "--showuse", "--showmemuse",
             "--showmeminfo", "vram", "--showpower", "--showclocks", "--csv"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return {"error": "rocm-smi failed"}

        temp = gpu_util = mem_util = mem_used = mem_total = power_draw = clock_sm = clock_mem = 0.0
        power_limit = 300.0  # rocm-smi doesn't always expose power limit easily

        for line in result.stdout.splitlines():
            if not line or line.startswith("device") or line.startswith("=="):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            # rocm-smi CSV format varies by version, parse what we can
            try:
                # Temperature (Junction is closest to nvidia's gpu temp)
                m = re.search(r'(\d+\.?\d*)', parts[1] if len(parts) > 1 else "")
                if m and temp == 0.0:
                    temp = float(m.group(1))
            except Exception:
                pass

        # Use JSON output for more reliable parsing if available
        json_result = subprocess.run(
            ["rocm-smi", "--showtemp", "--showuse", "--showmemuse",
             "--showmeminfo", "vram", "--showpower", "--showclocks", "--json"],
            capture_output=True, text=True, timeout=5
        )
        if json_result.returncode == 0:
            try:
                data = json.loads(json_result.stdout)
                # rocm-smi JSON uses card0, card1 etc as keys
                card = next(iter(data.values()))
                temp = float(card.get("Temperature (Sensor junction) (C)", 0))
                gpu_util = float(card.get("GPU use (%)", 0))
                mem_util = float(card.get("GPU memory use (%)", 0))
                vram_used = card.get("VRAM Total Used Memory (B)", 0)
                vram_total = card.get("VRAM Total Memory (B)", 0)
                mem_used = round(float(vram_used) / 1024 / 1024, 1)
                mem_total = round(float(vram_total) / 1024 / 1024, 1)
                power_draw = float(card.get("Average Graphics Package Power (W)", 0))
                clock_sm = float(card.get("sclk clock speed:", "0").replace("(", "").replace("Mhz)", "").strip() or 0)
                clock_mem = float(card.get("mclk clock speed:", "0").replace("(", "").replace("Mhz)", "").strip() or 0)
            except Exception:
                pass

        return {
            "name": name,
            "temp": temp,
            "gpu_util": gpu_util,
            "mem_util": mem_util,
            "mem_used": mem_used,
            "mem_total": mem_total,
            "power_draw": power_draw,
            "power_limit": power_limit,
            "clock_sm": clock_sm,
            "clock_mem": clock_mem,
            "vendor": "amd",
        }
    except Exception as e:
        return {"error": str(e)}

def get_gpu_stats():
    if GPU_TYPE == "nvidia":
        return get_gpu_stats_nvidia()
    elif GPU_TYPE == "amd":
        return get_gpu_stats_amd()
    else:
        return {"error": "no supported GPU found (nvidia-smi or rocm-smi required)"}

def get_cpu_stats():
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        parts = line.split()
        total = sum(int(x) for x in parts[1:8])
        idle = int(parts[4])
        prev = get_cpu_stats.__dict__.get('_last', (total, idle))
        get_cpu_stats._last = (total, idle)
        dt = total - prev[0]
        di = idle - prev[1]
        util = 0.0 if dt == 0 else round((1 - di / dt) * 100, 1)
        return {"cpu_util": max(0.0, util)}
    except Exception:
        return {"cpu_util": 0.0}

def get_mem_stats():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if parts[0] in ("MemTotal:", "MemAvailable:"):
                    info[parts[0].rstrip(":")] = int(parts[1])
        total = info.get("MemTotal", 0) / 1024 / 1024
        avail = info.get("MemAvailable", 0) / 1024 / 1024
        used = total - avail
        return {
            "mem_total_gb": round(total, 1),
            "mem_used_gb": round(used, 1),
            "mem_util": round((used / total) * 100, 1) if total > 0 else 0,
        }
    except Exception:
        return {"mem_total_gb": 0, "mem_used_gb": 0, "mem_util": 0}

def get_ollama_stats():
    try:
        with urlopen(OLLAMA_API + "/api/ps", timeout=3) as r:
            data = json.loads(r.read())
        models = data.get("models", [])
        if not models:
            return {"status": "idle", "models": []}
        result = []
        for m in models:
            size_vram = m.get("size_vram", 0)
            size = m.get("size", 0)
            details = m.get("details", {})
            result.append({
                "name": m.get("name", "unknown"),
                "size_gb": round(size / 1024**3, 2),
                "vram_gb": round(size_vram / 1024**3, 2),
                "cpu_gb": round((size - size_vram) / 1024**3, 2),
                "context_length": m.get("context_length", 0),
                "param_size": details.get("parameter_size", "?"),
                "quant": details.get("quantization_level", "?"),
            })
        return {"status": "loaded", "models": result}
    except URLError:
        return {"status": "unreachable", "models": []}
    except Exception as e:
        return {"status": "error: " + str(e), "models": []}

def get_layer_stats():
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", "500", "nomad_ollama"],
            capture_output=True, text=True, timeout=5
        )
        log = result.stdout + result.stderr
        gpu_layers = total_layers = kv_cache = eval_rate = prompt_rate = None
        for line in reversed(log.splitlines()):
            if gpu_layers is None:
                m = re.search(r"offloaded (\d+)/(\d+) layers to GPU", line)
                if m:
                    gpu_layers = int(m.group(1))
                    total_layers = int(m.group(2))
            if kv_cache is None:
                m = re.search(r'kv cache.*size="?([\d.]+)\s*(\w+)"?', line)
                if m:
                    val = float(m.group(1))
                    unit = m.group(2).upper()
                    kv_cache = round(val if "GIB" in unit or "GB" in unit else val / 1024, 2)
            if eval_rate is None:
                m = re.search(r'eval rate.*?(\d+\.?\d*)\s*tokens/s', line)
                if m:
                    eval_rate = round(float(m.group(1)), 1)
            if prompt_rate is None:
                m = re.search(r'prompt eval rate.*?(\d+\.?\d*)\s*tokens/s', line)
                if m:
                    prompt_rate = round(float(m.group(1)), 1)
            if all(x is not None for x in [gpu_layers, kv_cache, eval_rate, prompt_rate]):
                break
        return {
            "gpu_layers": gpu_layers,
            "total_layers": total_layers,
            "kv_cache_gb": kv_cache,
            "eval_rate": eval_rate,
            "prompt_rate": prompt_rate,
        }
    except Exception:
        return {"gpu_layers": None, "total_layers": None, "kv_cache_gb": None, "eval_rate": None, "prompt_rate": None}


HTML = (
    '<!DOCTYPE html><html lang="en"><head>'
    '<meta charset="UTF-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    '<title>NOMAD Monitor</title>'
    '<style>'
    '*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}'
    ':root{'
    '--bg:#0e0e10;--surface:#18181c;--border:#2a2a32;'
    '--text:#e8e8ec;--muted:#6b6b78;'
    '--green:#22c55e;--amber:#f59e0b;--red:#ef4444;'
    '--blue:#3b82f6;--purple:#a855f7;--cyan:#06b6d4;'
    '}'
    'body{background:var(--bg);color:var(--text);font-family:"IBM Plex Mono",monospace;font-size:13px;padding:20px;}'
    'header{display:flex;align-items:baseline;gap:16px;margin-bottom:24px;border-bottom:1px solid var(--border);padding-bottom:16px;}'
    'h1{font-size:16px;font-weight:500;color:var(--cyan);letter-spacing:.08em;text-transform:uppercase;}'
    '#dot{width:8px;height:8px;border-radius:50%;background:var(--green);display:inline-block;animation:pulse 2s infinite;}'
    '@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}'
    '#ts{font-size:11px;color:var(--muted);margin-left:auto;}'
    '.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));margin-bottom:12px;}'
    '.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;}'
    '.ct{font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:14px;}'
    '.row{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;}'
    '.lbl{color:var(--muted);font-size:12px;}'
    '.val{font-size:13px;font-weight:500;}'
    '.bw{background:#222228;border-radius:3px;height:6px;margin-top:4px;overflow:hidden;}'
    '.bf{height:100%;border-radius:3px;transition:width .6s ease;}'
    '.bg{background:var(--green)}.ba{background:var(--amber)}.br2{background:var(--red)}'
    '.bp{background:var(--purple)}.bb{background:var(--blue)}'
    '.cg{color:var(--green)}.ca{color:var(--amber)}.cr{color:var(--red)}'
    '.cb{color:var(--blue)}.cc{color:var(--cyan)}.cp{color:var(--purple)}.cm{color:var(--muted)}'
    '.full{grid-column:1/-1;}'
    '.mc{background:#13131a;border:1px solid var(--border);border-radius:6px;padding:14px;margin-bottom:10px;}'
    '.mn{font-size:13px;color:var(--cyan);margin-bottom:10px;word-break:break-all;}'
    '.mg{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px;}'
    '.ml{color:var(--muted);font-size:11px;margin-bottom:2px;}'
    '.mv{font-size:12px;font-weight:500;}'
    '.lbw{background:#222228;border-radius:3px;height:10px;margin:8px 0 4px;overflow:hidden;position:relative;}'
    '.lgpu{height:100%;background:var(--green);border-radius:3px;position:absolute;left:0;top:0;transition:width .6s ease;}'
    '.lcpu{height:100%;background:var(--amber);border-radius:3px;position:absolute;top:0;transition:width .6s ease;}'
    '.idle{color:var(--muted);font-size:12px;padding:20px 0;text-align:center;}'
    '.badge{display:inline-block;font-size:10px;padding:2px 7px;border-radius:3px;margin-left:8px;vertical-align:middle;}'
    '.bdg{background:#14532d;color:var(--green)}.bda{background:#451a03;color:var(--amber)}'
    '.hw{position:relative;width:100%;height:80px;margin-top:8px;}'
    'canvas{display:block;}'
    '</style></head><body>'
    '<header><span id="dot"></span><h1>NOMAD Monitor</h1><span id="ts">--</span></header>'
    '<div class="grid">'
    '<div class="card">'
    '<div class="ct">GPU</div>'
    '<div id="gname" style="font-size:12px;color:var(--muted);margin-bottom:12px;">--</div>'
    '<div class="row"><span class="lbl">utilization</span><span class="val" id="gutil">--%</span></div>'
    '<div class="bw"><div class="bf bg" id="bgutil" style="width:0%"></div></div>'
    '<div class="row" style="margin-top:10px;"><span class="lbl">temperature</span><span class="val" id="gtemp">--&deg;C</span></div>'
    '<div class="row"><span class="lbl">power draw</span><span class="val" id="gpow">-- W</span></div>'
    '<div class="bw"><div class="bf ba" id="bgpow" style="width:0%"></div></div>'
    '<div class="row" style="margin-top:10px;"><span class="lbl">SM clock</span><span class="val cm" id="gsm">-- MHz</span></div>'
    '<div class="row"><span class="lbl">mem clock</span><span class="val cm" id="gmem">-- MHz</span></div>'
    '</div>'
    '<div class="card">'
    '<div class="ct">VRAM</div>'
    '<div class="row"><span class="lbl">used / total</span><span class="val" id="vused">-- / -- GiB</span></div>'
    '<div class="bw"><div class="bf bp" id="bvram" style="width:0%"></div></div>'
    '<div class="row" style="margin-top:12px;"><span class="lbl">utilization</span><span class="val" id="vutil">--%</span></div>'
    '<div style="margin-top:10px;"><div class="ct" style="margin-bottom:6px;">history (90s)</div>'
    '<div class="hw"><canvas id="vc"></canvas></div></div>'
    '</div>'
    '<div class="card">'
    '<div class="ct">CPU &amp; system RAM</div>'
    '<div class="row"><span class="lbl">CPU utilization</span><span class="val" id="cutil">--%</span></div>'
    '<div class="bw"><div class="bf bb" id="bcpu" style="width:0%"></div></div>'
    '<div class="row" style="margin-top:12px;"><span class="lbl">RAM used / total</span><span class="val" id="rused">-- / -- GiB</span></div>'
    '<div class="bw"><div class="bf bb" id="bram" style="width:0%"></div></div>'
    '<div style="margin-top:10px;"><div class="ct" style="margin-bottom:6px;">CPU history (90s)</div>'
    '<div class="hw"><canvas id="cc"></canvas></div></div>'
    '</div>'
    '</div>'
    '<div class="grid">'
    '<div class="card full"><div class="ct">Ollama &mdash; loaded models</div>'
    '<div id="mlist"><div class="idle">waiting...</div></div>'
    '</div></div>'
    '<script>'
    'var N=90,vh=[],ch=[];'
    'for(var i=0;i<N;i++){vh.push(0);ch.push(0);}'
    'function bc(p){return p<60?"bg":p<85?"ba":"br2";}'
    'function tc(p){return p<60?"cg":p<85?"ca":"cr";}'
    'function setBar(id,pct,cls){'
    'var el=document.getElementById(id);'
    'el.style.width=Math.min(pct,100).toFixed(1)+"%";'
    'el.className="bf "+cls;}'
    'function setVal(id,text,cls){'
    'var el=document.getElementById(id);'
    'el.textContent=text;'
    'if(cls)el.className="val "+cls;}'
    'function spark(id,data,color){'
    'var c=document.getElementById(id);if(!c)return;'
    'var W=c.parentElement.offsetWidth||300;'
    'c.width=W;c.height=80;'
    'var ctx=c.getContext("2d");'
    'ctx.clearRect(0,0,W,80);'
    'var step=W/(data.length-1);'
    'ctx.beginPath();'
    'for(var i=0;i<data.length;i++){'
    'var x=i*step;var y=80-(data[i]/100)*76-2;'
    'if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);}'
    'ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.stroke();'
    'ctx.lineTo(W,80);ctx.lineTo(0,80);ctx.closePath();'
    'ctx.fillStyle=color+"22";ctx.fill();}'
    'function renderModels(o,l){'
    'if(o.status==="idle")return \'<div class="idle">no models loaded</div>\';'
    'if(o.status==="unreachable")return \'<div class="idle" style="color:var(--red)">ollama unreachable</div>\';'
    'var html="";'
    'for(var i=0;i<o.models.length;i++){'
    'var m=o.models[i];'
    'html+=\'<div class="mc">\';'
    'html+=\'<div class="mn">\'+m.name+\'</div>\';'
    'html+=\'<div class="mg">\';'
    'html+=\'<div><div class="ml">size</div><div class="mv cm">\'+m.size_gb+\' GiB</div></div>\';'
    'html+=\'<div><div class="ml">in VRAM</div><div class="mv cp">\'+m.vram_gb+\' GiB</div></div>\';'
    'html+=\'<div><div class="ml">in RAM</div><div class="mv \'+(m.cpu_gb>0?"ca":"cm")+\'">\'+m.cpu_gb+\' GiB</div></div>\';'
    'html+=\'<div><div class="ml">params</div><div class="mv cm">\'+m.param_size+\'</div></div>\';'
    'html+=\'<div><div class="ml">quant</div><div class="mv cm">\'+m.quant+\'</div></div>\';'
    'html+=\'<div><div class="ml">context</div><div class="mv cc">\'+m.context_length.toLocaleString()+\'</div></div>\';'
    'html+=\'</div>\';'
    'if(l.gpu_layers!==null&&l.total_layers!==null){'
    'var gl=l.gpu_layers,tl=l.total_layers,cl2=tl-gl;'
    'var gp=(gl/tl*100).toFixed(1);'
    'var cp=(cl2/tl*100).toFixed(1);'
    'var allGpu=gl===tl;'
    'var badge=allGpu?\'<span class="badge bdg">100% GPU</span>\':\'<span class="badge bda">CPU offload</span>\';'
    'html+=\'<div class="row"><span class="lbl">layers on GPU</span>\';'
    'html+=\'<span class="val \'+(allGpu?"cg":"ca")+\'">\'+gl+"/"+tl+badge+\'</span></div>\';'
    'html+=\'<div class="lbw"><div class="lgpu" style="width:\'+gp+\'%"></div>\';'
    'if(cl2>0)html+=\'<div class="lcpu" style="left:\'+gp+\'%;width:\'+cp+\'%"></div>\';'
    'html+=\'</div>\';'
    'html+=\'<div style="display:flex;gap:16px;margin-top:4px;font-size:11px;">\';'
    'html+=\'<span class="cg">&#9646; GPU \'+gl+\'</span>\';'
    'if(cl2>0)html+=\'<span class="ca">&#9646; CPU \'+cl2+\'</span>\';'
    'html+=\'</div>\';'
    'if(l.kv_cache_gb!==null){'
    'html+=\'<div class="row" style="margin-top:8px;"><span class="lbl">KV cache</span>\';'
    'html+=\'<span class="val cp">\'+l.kv_cache_gb+\' GiB</span></div>\';'
    '}}'
    'if(l.eval_rate!==null||l.prompt_rate!==null){'
    'html+=\'<div style="display:flex;gap:20px;margin-top:10px;padding-top:10px;border-top:1px solid #2a2a32;">\';'
    'if(l.eval_rate!==null){'
    'html+=\'<div><div class="ml">last generation speed</div><div class="mv cg">\'+l.eval_rate+\' tok/s</div></div>\';'
    '}'
    'if(l.prompt_rate!==null){'
    'html+=\'<div><div class="ml">last prompt eval speed</div><div class="mv cc">\'+l.prompt_rate+\' tok/s</div></div>\';'
    '}'
    'html+=\'</div>\';'
    '}'
    'html+=\'</div>\';}'
    'return html;}'
    'function poll(){'
    'fetch("/api/stats")'
    '.then(function(r){return r.json();})'
    '.then(function(d){'
    'var g=d.gpu,cpu=d.cpu,mem=d.mem,o=d.ollama,l=d.layers;'
    'if(g&&!g.error){'
    'document.getElementById("gname").textContent=g.name;'
    'setVal("gutil",g.gpu_util.toFixed(0)+"%",tc(g.gpu_util));'
    'setBar("bgutil",g.gpu_util,bc(g.gpu_util));'
    'var tc2=g.temp>80?"cr":g.temp>65?"ca":"cg";'
    'setVal("gtemp",g.temp.toFixed(0)+"\u00b0C",tc2);'
    'var pp=g.power_draw/g.power_limit*100;'
    'setVal("gpow",g.power_draw.toFixed(0)+" W / "+g.power_limit.toFixed(0)+" W",null);'
    'setBar("bgpow",pp,bc(pp));'
    'document.getElementById("gsm").textContent=g.clock_sm.toFixed(0)+" MHz";'
    'document.getElementById("gmem").textContent=g.clock_mem.toFixed(0)+" MHz";'
    'var vu=(g.mem_used/1024).toFixed(1);'
    'var vt=(g.mem_total/1024).toFixed(1);'
    'var vp=g.mem_used/g.mem_total*100;'
    'document.getElementById("vused").textContent=vu+" / "+vt+" GiB";'
    'setVal("vutil",vp.toFixed(1)+"%",tc(vp));'
    'setBar("bvram",vp,"bp");'
    'vh.push(vp);if(vh.length>N)vh.shift();'
    'spark("vc",vh,"#a855f7");}'
    'if(cpu){'
    'setVal("cutil",cpu.cpu_util.toFixed(0)+"%",tc(cpu.cpu_util));'
    'setBar("bcpu",cpu.cpu_util,bc(cpu.cpu_util));'
    'ch.push(cpu.cpu_util);if(ch.length>N)ch.shift();'
    'spark("cc",ch,"#3b82f6");}'
    'if(mem){'
    'document.getElementById("rused").textContent=mem.mem_used_gb.toFixed(1)+" / "+mem.mem_total_gb.toFixed(1)+" GiB";'
    'setBar("bram",mem.mem_util,bc(mem.mem_util));}'
    'document.getElementById("mlist").innerHTML=renderModels(o,l);'
    'document.getElementById("ts").textContent="updated "+new Date().toLocaleTimeString();'
    'document.getElementById("dot").style.background="var(--green)";'
    '})'
    '.catch(function(){'
    'document.getElementById("dot").style.background="var(--red)";'
    '});}'
    'poll();setInterval(poll,1000);'
    '</script></body></html>'
)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path == '/api/stats':
            data = {
                'gpu': get_gpu_stats(),
                'ollama': get_ollama_stats(),
                'layers': get_layer_stats(),
                'cpu': get_cpu_stats(),
                'mem': get_mem_stats(),
            }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    print("NOMAD Monitor running at http://0.0.0.0:" + str(PORT))
    print("Ctrl+C to stop")
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
