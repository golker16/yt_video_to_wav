# -*- coding: utf-8 -*-
"""
YouTube → MP4 + MP3/WAV GUI (PySide6)
- Descarga con yt-dlp (videos o playlists).
- Convierte audio a MP3 y/o WAV con ffmpeg.
- Opción para borrar el MP4 luego de convertir.
- Progreso y logs en vivo.
- Tema oscuro con qdarkstyle.
- Footer con "© 2025 Gabriel Golker".
- Ícono de ventana si existe assets/app.png o assets/app.ico.

Actualización:
- Detecta ffmpeg en varios lugares (junto al exe, ./ffmpeg/ffmpeg.exe, ./assets/ffmpeg.exe, PATH).
- Ejecuta ffmpeg usando listas de argumentos (no shlex) → robusto en Windows con rutas con espacios.

Nota legal: usa esto solo con contenido propio o con permiso.
"""

import sys, os, re, subprocess, threading
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


# ------------------ utilidades ------------------

def resource_path(rel: str) -> str:
    """Soporta PyInstaller (onefile/onedir) y ejecución normal."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return str(Path(base) / rel)
    return str(Path(__file__).parent / rel)

def which_ffmpeg() -> str:
    """
    Devuelve la ruta a ffmpeg:
    1) junto al exe (onedir): Path(sys.executable).parent/ffmpeg.exe
    2) ./ffmpeg/ffmpeg.exe
    3) ./assets/ffmpeg.exe
    4) en PATH del sistema
    """
    from shutil import which as which_cmd

    # 1) junto al exe (cuando está compilado)
    try:
        here = Path(sys.executable).parent
        cand = here / "ffmpeg.exe"
        if cand.exists():
            return str(cand)
    except Exception:
        pass

    # 2) carpeta ffmpeg/ local
    cand2 = Path(resource_path("ffmpeg/ffmpeg.exe"))
    if cand2.exists():
        return str(cand2)

    # 3) assets/
    cand3 = Path(resource_path("assets/ffmpeg.exe"))
    if cand3.exists():
        return str(cand3)

    # 4) PATH
    in_path = which_cmd("ffmpeg")
    if in_path:
        return in_path

    raise FileNotFoundError(
        "No se encontró ffmpeg.\n"
        "Pon ffmpeg.exe junto a app.exe (recomendado), o en ./ffmpeg/ffmpeg.exe, "
        "o ./assets/ffmpeg.exe, o añade ffmpeg al PATH del sistema."
    )

def run_process(args):
    """
    Ejecuta un proceso con lista de argumentos (seguro para rutas con espacios).
    Emite stdout+stderr línea a línea.
    """
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in proc.stdout:
        yield line.rstrip()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"Comando falló ({proc.returncode}): {' '.join(args)}")


# ------------------ threading / worker ------------------

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

    # Hook de progreso por ítem de yt-dlp
    def _hook(self, d):
        if self.stop_flag:
            raise KeyboardInterrupt("Cancelado por el usuario.")
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes') or 0
            pct = int(downloaded * 100 / total) if total else 0
            self.s.progress.emit(max(0, min(100, pct)))

    def _convert(self, mp4_path: Path):
        ffmpeg = which_ffmpeg()
        self.s.log.emit(f"ffmpeg: {ffmpeg}")
        stem = mp4_path.with_suffix('')
        do_mp3 = (self.choice in ('MP3', 'Ambos'))
        do_wav = (self.choice in ('WAV', 'Ambos'))

        if do_mp3:
            out_mp3 = str(stem) + ".mp3"
            args = [ffmpeg, "-y", "-i", str(mp4_path), "-vn", "-b:a", "320k", out_mp3]
            self.s.log.emit("$ " + " ".join(f'"{a}"' if " " in a else a for a in args))
            for line in run_process(args):
                self.s.log.emit(line)

        if do_wav:
            out_wav = str(stem) + ".wav"
            args = [ffmpeg, "-y", "-i", str(mp4_path), "-vn", "-ar", "44100", "-ac", "2", "-f", "wav", out_wav]
            self.s.log.emit("$ " + " ".join(f'"{a}"' if " " in a else a for a in args))
            for line in run_process(args):
                self.s.log.emit(line)

        if self.delete_mp4 and mp4_path.exists():
            try:
                mp4_path.unlink()
                self.s.log.emit(f"Eliminado MP4: {mp4_path.name}")
            except Exception as e:
                self.s.log.emit(f"No se pudo borrar {mp4_path.name}: {e}")

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
                    'preferedformat': 'mp4',  # (sic) nombre de clave histórico en yt-dlp
                }],
                'concurrent_fragment_downloads': 4,
            }

            # Prescan para estimar cantidad total de ítems (progreso global simple)
            total_items = 0
            prescan_opts = dict(ydl_opts)
            prescan_opts['skip_download'] = True
            with YoutubeDL(prescan_opts) as ydl:
                for url in self.urls:
                    info = ydl.extract_info(url, download=False)
                    if not info:
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

                    for e in entries:
                        title = e.get('title', 'video')
                        vid = e.get('id', 'id')
                        # Nombre esperado que genera yt-dlp con la plantilla
                        mp4_path = self.outdir / f"{title} [{vid}].mp4"

                        # Si por caracteres especiales no coincide exactamente, buscar por ID
                        if not mp4_path.exists():
                            candidates = list(self.outdir.glob(f"*[{vid}]*.mp4"))
                            if candidates:
                                mp4_path = candidates[0]

                        if mp4_path.exists():
                            self.s.log.emit(f"Convertir: {mp4_path.name}")
                            self._convert(mp4_path)
                        else:
                            self.s.log.emit(f"No se encontró MP4 esperado para {title} [{vid}]")

                        processed_items += 1
                        pct_global = int(processed_items * 100 / total_items)
                        self.s.progress.emit(max(0, min(100, pct_global)))

            self.s.log.emit("Completado.")
        except FileNotFoundError as e:
            # Mensaje claro si falta ffmpeg
            self.s.log.emit(f"Error: {e}")
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

        # Carpeta de salida + selector
        row_out = QHBoxLayout()
        self.ed_out = QLineEdit(str(Path.cwd() / "salida"))
        btn_browse = QPushButton("Elegir carpeta…")
        btn_browse.clicked.connect(self.choose_dir)
        row_out.addWidget(QLabel("Carpeta de salida:"))
        row_out.addWidget(self.ed_out, 1)
        row_out.addWidget(btn_browse)
        root.addLayout(row_out)

        # Formato y opciones
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

        # Plantilla de nombre
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
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyside6'))  # tema oscuro
    # Ícono global
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

