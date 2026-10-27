"""Assemble the Docker lab report and print it to PDF.

    python report/docker/build_report.py

template.html placeholders:
  {{SHOT:name|caption}}         terminal screenshot  screenshots/name.png
  {{BROWSER:name|url|caption}}  browser screenshot   screenshots/name.png, with its URL above
  {{FILE:path}}                 a repository file, verbatim
  {{COMMANDS}}                  every docker command from logs/*.txt, in the order run
  {{UNIQUE}}                    table rows from UNIQUE below
"""

import html
import os
import re
import subprocess

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUT_HTML = os.path.join(HERE, "Docker_Report.html")
OUT_PDF = os.path.join(ROOT, "report", "Docker_Containerisation_Report.pdf")

UNIQUE = [
    ("docker --version", "Show the Docker CLI version"),
    ("docker version", "Full client and server (engine, containerd, runc) versions: confirms the install end to end"),
    ("docker run --rm hello-world", "Official post-install test: pull a tiny image and run it"),
    ("docker pull IMAGE", "Download an image from Docker Hub without running it (used to retry a failed pull)"),
    ("docker compose version", "Show the Compose plugin version"),
    ("docker info --format '{{...}}'", "Check that the engine is reachable; show engine version, OS, kernel and CPUs"),
    ("docker ps", "List running containers (first command; showed the engine was down)"),
    ("docker compose config --quiet / --services", "Validate the compose file (after .env substitution) and list its services"),
    ("docker build --target test -t proximity-api:test .", "Build only up to the named stage of a multi-stage Dockerfile and tag the image"),
    ("docker build -q / --progress=plain", "Quiet build that prints only the image ID / full, unabbreviated build log"),
    ("docker run --rm IMAGE [CMD]", "Run a one-off container and delete it on exit (test suite, network checks)"),
    ("docker run --rm --network NET IMAGE", "Run a one-off container on a chosen network (MTU / host-network test)"),
    ("docker compose up -d --build", "Build images if needed, create network and volume, start all services detached"),
    ("docker compose up -d [SERVICE]", "Start or recreate the stack, or one service, from existing images"),
    ("docker compose build SERVICE", "Rebuild one service's image without starting it"),
    ("docker compose ps [-q]", "Status and health of the project's containers / just their IDs"),
    ("docker compose port gateway 80", "Show which host address and port a container port is published on"),
    ("docker images 'proximity-*'", "List the built images and their sizes"),
    ("docker compose exec SERVICE CMD", "Run a command inside a running service container (env, user, DNS, files)"),
    ("docker network inspect NET --format", "Show a network's driver, subnet and attached containers"),
    ("docker network create --opt …mtu=1400 NET / docker network rm NET", "Create and remove a test bridge network with a lower MTU"),
    ("docker compose logs --tail N SERVICE", "Show the last N log lines of a service"),
    ("docker stats --no-stream $(docker compose ps -q)", "One-off CPU, memory, network and PID usage of this project's containers"),
    ("docker volume ls --filter name=…", "List volumes matching a name"),
    ("docker compose stop SERVICE", "Stop a service gracefully (SIGTERM, then SIGKILL after 10 s)"),
    ("docker compose down", "Stop and remove the project's containers and network (named volumes kept)"),
]


SHOT_SCALE = 0.66  # CSS px per screenshot px (captured at 2x), so all terminal text prints at one size


def shot(name, caption, url=None):
    cls = "browser" if url else "shot"
    dpr = 1 if name.startswith("real/") else 2  # real window captures are 1x, rendered ones 2x
    with Image.open(os.path.join(HERE, "screenshots", name + ".png")) as im:
        width = round(im.width / dpr * SHOT_SCALE)
    style = f' style="width:min(100%,{width}px)"'
    top = f'<div class="url"{style}>{url}</div>' if url else ""
    cap = ""
    if caption:
        cap = re.sub(r"^(Figure [0-9a-z]+\.)", r"<b>\1</b>", caption)
        cap = f"<figcaption>{cap}</figcaption>"
    return (f'<figure>{top}<img class="{cls}" src="screenshots/{name}.png" alt="{html.escape(name)}"{style}>'
            f'{cap}</figure>')


def strip_filters(cmd):
    """Drop top-level `| grep/tail/head …` pipes, `2>&1` and trailing `# comments`; quoted text is kept."""
    out, i, quote = [], 0, None
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and cmd[i - 1:i] == " ":
            break
        elif ch == "|" and re.match(r"\|\s*(?:grep|tail|head)\b", cmd[i:]):
            j, q = i, None  # skip the filter up to the next top-level ';' or '&&'
            while j < len(cmd) and (q or not (cmd[j] == ";" or cmd.startswith("&&", j))):
                if q:
                    q = None if cmd[j] == q else q
                elif cmd[j] in "'\"":
                    q = cmd[j]
                j += 1
            i = j
            continue
        out.append(ch)
        i += 1
    return re.sub(r"\s*2>&1|\s+(?=;)", "", "".join(out)).strip()


def commands():
    prev, out = None, []
    logs = [os.path.join(HERE, "logs", fn) for fn in os.listdir(os.path.join(HERE, "logs"))]
    for path in sorted(logs, key=os.path.getmtime):  # log files keep the time each command ran
        lines = open(path, encoding="utf-8").read().split("\n")
        for n, line in enumerate(lines):
            if not (line.startswith("$ ") and "docker" in line):
                continue
            cmd = line[2:]
            while cmd.count("'") % 2 and n + 1 < len(lines):  # command continues on the next line
                n += 1
                cmd += "\n" + lines[n]
            cmd = strip_filters(cmd)
            if cmd != prev:
                out.append(html.escape(cmd))
            prev = cmd
    return "\n".join(out)


def build():
    page = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    page = re.sub(r"\{\{SHOT:([^|}]+)\|([^}]*)\}\}", lambda m: shot(m[1], m[2]), page)
    page = re.sub(r"\{\{BROWSER:([^|}]+)\|([^|}]+)\|([^}]*)\}\}", lambda m: shot(m[1], m[3], m[2]), page)
    page = re.sub(r"\{\{FILE:([^}]+)\}\}",
                  lambda m: html.escape(open(os.path.join(ROOT, m[1]), encoding="utf-8").read().rstrip()), page)
    page = page.replace("{{COMMANDS}}", commands())
    page = page.replace("{{UNIQUE}}", "\n".join(
        f"    <tr><td><code>{html.escape(c)}</code></td><td>{html.escape(p)}</td></tr>" for c, p in UNIQUE))
    missing = re.findall(r"\{\{(?:SHOT|BROWSER|FILE|COMMANDS|UNIQUE)[^}]*\}\}", page)
    assert not missing, missing
    for img in re.findall(r'src="(screenshots/[^"]+)"', page):
        assert os.path.isfile(os.path.join(HERE, img)), img
    open(OUT_HTML, "w", encoding="utf-8").write(page)

    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=15000", f"--print-to-pdf={OUT_PDF}",
                    "file:///" + OUT_HTML.replace("\\", "/")], check=True, capture_output=True)
    print("wrote", OUT_HTML)
    print("wrote", OUT_PDF)


if __name__ == "__main__":
    build()
