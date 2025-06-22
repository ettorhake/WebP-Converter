import sys
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                            QHBoxLayout, QPushButton, QLabel, QFileDialog,
                            QProgressBar, QSpinBox, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
import cv2
from PIL import Image
import os
import shutil

class ConversionThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, files, quality, output_dir):
        super().__init__()
        self.files = files
        self.quality = quality
        self.output_dir = output_dir

    def run(self):
        try:
            total_files = len(self.files)
            for i, file_path in enumerate(self.files, 1):
                try:
                    self.convert_file(file_path)
                    self.progress.emit(int((i / total_files) * 100))
                except Exception as e:
                    self.error.emit(f"Erreur lors de la conversion de {file_path}: {str(e)}")
            self.finished.emit()
        except Exception as e:
            self.error.emit(f"Erreur générale: {str(e)}")

    def convert_file(self, file_path):
        extension = file_path.suffix.lower()
        output_path = Path(self.output_dir) / f"{file_path.stem}.webp"

        if extension in ['.jpg', '.jpeg', '.png', '.bmp', '.gif']:
            self.convert_image(file_path, output_path)
        elif extension in ['.mp4', '.avi', '.mov', '.mkv']:
            self.convert_video(file_path, output_path)
        else:
            raise ValueError(f"Format non supporté: {extension}")

    def is_animated(self, image):
        try:
            image.seek(1)
            return True
        except EOFError:
            return False
        finally:
            image.seek(0)

    def get_frame_duration(self, image, frame_number):
        try:
            # Essaie d'obtenir la durée spécifique de la frame
            duration = image.info.get('duration', None)
            if duration is None and 'loop' in image.info:
                # Pour les PNG animés (APNG)
                duration = image.info.get('duration', 100)  # 100ms par défaut si non spécifié
            return duration if duration is not None else 100  # 100ms par défaut
        except:
            return 100  # 100ms par défaut si erreur

    def convert_image(self, input_path, output_path):
        with Image.open(input_path) as img:
            # Vérifier si l'image est animée
            if self.is_animated(img):
                frames = []
                durations = []
                
                try:
                    while True:
                        # Préserver le mode de couleur et la transparence
                        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                            current_frame = img.convert('RGBA')
                        else:
                            current_frame = img.convert('RGB')
                        
                        frames.append(current_frame)
                        durations.append(self.get_frame_duration(img, img.tell()))
                        img.seek(img.tell() + 1)
                except EOFError:
                    pass

                if frames:
                    # Calculer la durée moyenne des frames pour les cas où les durées sont variables
                    avg_duration = sum(durations) / len(durations)
                    
                    # Sauvegarder en tant que WebP animé
                    frames[0].save(
                        output_path,
                        'WEBP',
                        append_images=frames[1:],
                        save_all=True,
                        duration=durations,  # Utiliser les durées originales
                        loop=0,  # 0 = boucle infinie
                        quality=self.quality,
                        minimize_size=True,  # Optimiser la taille
                        lossless=self.quality >= 95  # Mode sans perte si qualité ≥ 95
                    )
            else:
                # Image statique
                if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                    img = img.convert('RGBA')
                else:
                    img = img.convert('RGB')
                img.save(output_path, 'WEBP', quality=self.quality, lossless=self.quality >= 95)

    def convert_video(self, input_path, output_path):
        cap = cv2.VideoCapture(str(input_path))
        
        # Obtenir le framerate original
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30  # Valeur par défaut si le framerate ne peut pas être détecté
        
        frame_duration = int(1000 / fps)  # Conversion en millisecondes
        frames = []
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                    
                # Conversion BGR vers RGB et création de l'image PIL
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)
                frames.append(pil_image)
                
                # Libérer de la mémoire si trop de frames sont accumulées
                if len(frames) > 300:  # Traitement par lots pour les longues vidéos
                    self.save_webp_animation(frames, output_path, frame_duration, is_final=False)
                    frames = frames[-1:]  # Garder la dernière frame pour la continuité
        finally:
            cap.release()

        if frames:
            self.save_webp_animation(frames, output_path, frame_duration, is_final=True)

    def save_webp_animation(self, frames, output_path, frame_duration, is_final=True):
        if not frames:
            return
            
        save_params = {
            'format': 'WEBP',
            'append_images': frames[1:],
            'save_all': True,
            'duration': frame_duration,
            'loop': 0,
            'quality': self.quality,
            'minimize_size': True,
            'lossless': self.quality >= 95
        }
        
        if is_final:
            frames[0].save(output_path, **save_params)
        else:
            # Pour les sauvegardes intermédiaires, utiliser un fichier temporaire
            temp_path = output_path.with_suffix('.temp.webp')
            frames[0].save(temp_path, **save_params)
            # Fusionner avec le fichier existant si nécessaire
            if output_path.exists() and temp_path.exists():
                # TODO: Implement WebP merging if needed
                shutil.move(temp_path, output_path)
            elif temp_path.exists():
                shutil.move(temp_path, output_path)

class DropArea(QWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        layout = QVBoxLayout()
        self.label = QLabel("Glissez-déposez vos fichiers ici\nou cliquez sur 'Ouvrir'")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        self.setLayout(layout)
        self.setStyleSheet("""
            QWidget {
                border: 2px dashed #aaa;
                border-radius: 5px;
                padding: 20px;
                background-color: #f8f9fa;
            }
        """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        files = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        self.files_dropped.emit(files)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.files = []
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Convertisseur WebP')
        self.setMinimumSize(500, 300)

        # Widget central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Zone de dépôt
        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self.add_files)
        layout.addWidget(self.drop_area)

        # Contrôles
        controls_layout = QHBoxLayout()

        # Bouton Ouvrir
        open_button = QPushButton('Ouvrir')
        open_button.clicked.connect(self.open_files)
        controls_layout.addWidget(open_button)

        # Qualité
        controls_layout.addWidget(QLabel('Qualité:'))
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(80)
        controls_layout.addWidget(self.quality_spin)

        # Bouton Convertir
        self.convert_button = QPushButton('Convertir')
        self.convert_button.clicked.connect(self.start_conversion)
        self.convert_button.setEnabled(False)
        controls_layout.addWidget(self.convert_button)

        layout.addLayout(controls_layout)

        # Barre de progression
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Étiquette fichiers
        self.files_label = QLabel('Aucun fichier sélectionné')
        layout.addWidget(self.files_label)

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            'Sélectionner des fichiers',
            '',
            'Images/Vidéos (*.jpg *.jpeg *.png *.gif *.bmp *.mp4 *.avi *.mov *.mkv)'
        )
        self.add_files([Path(f) for f in files])

    def add_files(self, new_files):
        self.files.extend(new_files)
        self.files_label.setText(f'{len(self.files)} fichier(s) sélectionné(s)')
        self.convert_button.setEnabled(len(self.files) > 0)

    def start_conversion(self):
        if not self.files:
            return

        output_dir = Path(QFileDialog.getExistingDirectory(
            self, 'Sélectionner le dossier de destination'))
        
        if not output_dir.as_posix():
            return

        self.progress_bar.setVisible(True)
        self.convert_button.setEnabled(False)
        
        self.conversion_thread = ConversionThread(
            self.files,
            self.quality_spin.value(),
            output_dir
        )
        self.conversion_thread.progress.connect(self.progress_bar.setValue)
        self.conversion_thread.finished.connect(self.conversion_finished)
        self.conversion_thread.error.connect(self.show_error)
        self.conversion_thread.start()

    def conversion_finished(self):
        self.progress_bar.setVisible(False)
        self.convert_button.setEnabled(True)
        self.files = []
        self.files_label.setText('Aucun fichier sélectionné')
        QMessageBox.information(self, 'Succès', 'Conversion terminée !')

    def show_error(self, message):
        QMessageBox.warning(self, 'Erreur', message)

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Style moderne
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
