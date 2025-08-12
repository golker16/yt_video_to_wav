# -*- coding: utf-8 -*-
"""
YouTube → MP4 + MP3/WAV GUI (PySide6)
- Descarga con yt-dlp (videos individuales o playlists).
- Convierte audio a MP3 y/o WAV con ffmpeg.
- Opción para borrar el MP4 luego de convertir.
- Progreso y logs en vivo.
- Tema oscuro con qdarkstyle.
- Ventana muestra "© 2025 Gabriel Golker" en el footer.
- Setea ícono de ventana si existe assets/app.png o assets/app.ico.

Nota legal: usa esto solo con contenido propio o con permiso.
"""

import sys, os, re, shlex, subprocess, threading
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QPlainTextEdit, QProgressBar, QComboBox, QCheckBox,
    QFileDialog, QMessageBox
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt, Signal, QObject

import qdarkstyle
from yt_dlp import YoutubeDL

# ------------------ helpers ------------------

def resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return str(Path(base) / rel)
    return str(Path(__file__).parent / rel)

def which_ffmpeg() -> str:
    # Intentar 'ffmpeg' en PATH
    return 'ffmpeg'

def run_cmd(cmd: str):
    proc = subprocess.Popen(
        shlex.split(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    for line in proc.stdout:
        yield line.rstrip()
    proc.wait()
    returncode = proc.returncode
    if returncode != 0:
        raise RuntimeError(f"Comando falló ({returncode}): {cmd}")

# ------------------ worker ------------------

class Signals(QObject):
    log = Signal(str)
    progress = Signal(int)   # 0-100
    enable_ui = Signal(bool)
    done = Signal()

class DownloaderThread(threading.Thread):
    def __init__(self, urls, outdir, choice, delete_mp4, filename_template, signals: Signals):
        super().__init__(daemon=True)
        self.urls = [u.strip() for u in urls.splitlines() if u.strip()]
        self.outdir = Path(outdir)
        self.choice = choice   # "MP3", "WAV", "Ambos"
        self.delete_mp4 = delete_mp4
        self.template = filename_template
        self.s = signals
        self.stop_flag = False

    def stop(self):
        self.stop_flag = True

    # yt-dlp progress hook (por item)
    def _hook(self, d):
        if self.stop_flag:
            raise KeyboardInterrupt("Cancelado por el usuario.")
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes') or 0
            pct = int(downloaded * 100 / total) if total else 0
            self.s.progress.emit(min(max(pct, 0), 100))

    def _convert(self, mp4_path: Path):
        ffmpeg = which_ffmpeg()
        stem = mp4_path.with_suffix('')
        do_mp3 = (self.choice in ('MP3', 'Ambos'))
        do_wav = (self.choice in ('WAV', 'Ambos'))

        if do_mp3:
            cmd = f'{ffmpeg} -y -i "{mp4_path}" -vn -b:a 320k "{stem}.mp3"'
            self.s.log.emit(f'$ {cmd}')
            for line in run_cmd(cmd):
                self.s.log.emit(line)

        if do_wav:
            cmd = f'{ffmpeg} -y -i "{mp4_path}" -vn -ar 44100 -ac 2 -f wav "{stem}.wav"'
            self.s.log.emit(f'$ {cmd}')
            for line in run_cmd(cmd):
                self.s.log.emit(line)

        if self.delete_mp4 and mp4_path.exists():
            try:
                mp4_path.unlink()
                self.s.log.emit(f'Eliminado MP4: {mp4_path.name}')
            except Exception as e:
                self.s.log.emit(f'No se pudo borrar {mp4_path.name}: {e}')

    def run(self):
        try:
            self.s.enable_ui.emit(False)
            self.outdir.mkdir(parents=True, exist_ok=True)

            ydl_opts = {
                'outtmpl': str(self.outdir / (self.template + ".%(ext)s")),
                'noplaylist': False,
                'ignoreerrors': True,
                'merge_output_format': 'mp4',
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'progress_hooks': [self._hook],
                'postprocessors': [{
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': 'mp4',
                }],
                'concurrent_fragment_downloads': 4,
            }

            # Recuento estimado para progreso global
            total_items = 0
            # Pre-scan rápido de playlists: yt-dlp puede extraer info sin bajar
            prescan_opts = dict(ydl_opts)
            prescan_opts['skip_download'] = True
            with YoutubeDL(prescan_opts) as ydl:
                for url in self.urls:
                    info = ydl.extract_info(url, download=False)
                    if info is None:
                        continue
                    if 'entries' in info and info['entries']:
                        total_items += sum(1 for e in info['entries'] if e)
                    else:
                        total_items += 1
            total_items = max(total_items, 1)
            processed_items = 0

            with YoutubeDL(ydl_opts) as ydl:
                for url in self.urls:
                    if self.stop_flag:
                        break
                    self.s.log.emit("="*80)
                    self.s.log.emit(f"URL: {url}")
                    info = ydl.extract_info(url, download=True)
                    entries = []
                    if info is None:
                        continue
                    if 'entries' in info and info['entries']:
                        for e in info['entries']:
                            if e:
                                entries.append(e)
                    else:
                        entries.append(info)

                    # Para cada entrada, construir el nombre esperado .mp4 y convertir
                    for e in entries:
                        title = e.get('title', 'video')
                        vid = e.get('id', 'id')
                        mp4_path = self.outdir / f"{title} [{vid}].mp4"
                        # Si por caracteres raros no coincide, buscar cualquier .mp4 con el id
                        if not mp4_path.exists():
                            for cand in self.outdir.glob(f"*[{vid}]*.mp4"):
                                mp4_path = cand
                                break

                        if mp4_path.exists():
                            self.s.log.emit(f"Convertir: {mp4_path.name}")
                            self._convert(mp4_path)
                        else:
                            self.s.log.emit(f"No se encontró MP4 esperado para {title} [{vid}]")

                        processed_items += 1
                        # Progreso global aproximado por ítems
                        pct_global = int(processed_items * 100 / total_items)
                        self.s.progress.emit(min(max(pct_global, 0), 100))

            self.s.log.emit("Completado.")
        except KeyboardInterrupt:
            self.s.log.emit("Cancelado por el usuario.")
        except Exception as e:
            self.s.log.emit(f"Error: {e}")
        finally:
            self.s.enable_ui.emit(True)
            self.s.done.emit()

# ------------------ GUI ------------------

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube → MP4 + MP3/WAV")
        self.resize(900, 650)

        # Ícono si existe
        ico_png = Path(resource_path("assets/app.png"))
        ico_ico = Path(resource_path("assets/app.ico"))
        if ico_png.exists():
            self.setWindowIcon(QIcon(str(ico_png)))
        elif ico_ico.exists():
            self.setWindowIcon(QIcon(str(ico_ico)))

        root = QVBoxLayout(self)

        # URLs
        root.addWidget(QLabel("URLs (una por línea):"))
        self.txt_urls = QTextEdit()
        self.txt_urls.setPlaceholderText("Pega aquí uno o varios enlaces de YouTube (videos o playlists).")
        root.addWidget(self.txt_urls)

        # Output dir + selector
        row_out = QHBoxLayout()
        self.ed_out = QLineEdit(str(Path.cwd() / "salida"))
        btn_browse = QPushButton("Elegir carpeta…")
        btn_browse.clicked.connect(self.choose_dir)
        row_out.addWidget(QLabel("Carpeta de salida:"))
        row_out.addWidget(self.ed_out, 1)
        row_out.addWidget(btn_browse)
        root.addLayout(row_out)

        # Formato de salida y opciones
        row_fmt = QHBoxLayout()
        row_fmt.addWidget(QLabel("Audio:"))
        self.cmb_audio = QComboBox()
        self.cmb_audio.addItems(["MP3", "WAV", "Ambos"])
        row_fmt.addWidget(self.cmb_audio)

        self.chk_delete = QCheckBox("Borrar MP4 al finalizar")
        self.chk_delete.setChecked(True)
        row_fmt.addWidget(self.chk_delete)

        row_fmt.addStretch(1)
        root.addLayout(row_fmt)

        # Template de nombre
        row_tpl = QHBoxLayout()
        row_tpl.addWidget(QLabel("Plantilla de nombre:"))
        self.ed_tpl = QLineEdit("%(title)s [%(id)s]")
        row_tpl.addWidget(self.ed_tpl)
        root.addLayout(row_tpl)

        # Botones
        row_btns = QHBoxLayout()
        self.btn_start = QPushButton("Iniciar")
        self.btn_start.clicked.connect(self.start)
        self.btn_stop = QPushButton("Cancelar")
        self.btn_stop.clicked.connect(self.stop)
        row_btns.addWidget(self.btn_start)
        row_btns.addWidget(self.btn_stop)
        row_btns.addStretch(1)
        root.addLayout(row_btns)

        # Progreso
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        root.addWidget(self.bar)

        # Logs
        root.addWidget(QLabel("Logs:"))
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        root.addWidget(self.logs, 1)

        # Footer
        footer = QLabel("© 2025 Gabriel Golker")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("padding: 8px; opacity: 0.8;")
        root.addWidget(footer)

        # Señales
        self.signals = Signals()
        self.signals.log.connect(self.append_log)
        self.signals.progress.connect(self.bar.setValue)
        self.signals.enable_ui.connect(self.enable_ui)

        self.worker = None

    def choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Elegir carpeta de salida", str(Path(self.ed_out.text()).resolve()))
        if d:
            self.ed_out.setText(d)

    def enable_ui(self, enabled: bool):
        for w in (self.txt_urls, self.ed_out, self.cmb_audio, self.chk_delete, self.ed_tpl, self.btn_start):
            w.setEnabled(enabled)

    def append_log(self, text: str):
        self.logs.appendPlainText(text)

    def start(self):
        urls = self.txt_urls.toPlainText().strip()
        if not urls:
            QMessageBox.warning(self, "Falta URL", "Pega al menos una URL de YouTube (video o playlist).")
            return
        outdir = self.ed_out.text().strip()
        choice = self.cmb_audio.currentText()
        delete_mp4 = self.chk_delete.isChecked()
        template = self.ed_tpl.text().strip() or "%(title)s [%(id)s]"

        self.logs.clear()
        self.bar.setValue(0)

        self.worker = DownloaderThread(
            urls=urls,
            outdir=outdir,
            choice=choice,
            delete_mp4=delete_mp4,
            filename_template=template,
            signals=self.signals
        )
        self.worker.start()

    def stop(self):
        if self.worker and self.worker.is_alive():
            self.worker.stop()
            self.append_log("Solicitando cancelación…")

def main():
    app = QApplication(sys.argv)
    # Tema oscuro
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyside6'))
    # Ícono global si existe
    ico_png = Path(resource_path("assets/app.png"))
    ico_ico = Path(resource_path("assets/app.ico"))
    if ico_png.exists():
        app.setWindowIcon(QIcon(str(ico_png)))
    elif ico_ico.exists():
        app.setWindowIcon(QIcon(str(ico_ico)))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
