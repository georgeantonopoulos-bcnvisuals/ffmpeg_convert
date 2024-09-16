import sys
import os
import glob
from PyQt5 import QtWidgets, QtGui, QtCore
import subprocess

class FFmpegConverter(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.sequenceFiles = []
        self.inputDirectory = ''
        self.initUI()
        
    def initUI(self):
        # Set window properties
        self.setWindowTitle('FFmpeg EXR Converter')
        self.setGeometry(100, 100, 600, 400)
        
        # Apply dark theme
        self.setStyleSheet('background-color: #2e2e2e; color: #ffffff;')
        
        # Create layout
        layout = QtWidgets.QVBoxLayout()
        
        # Input file selection
        self.inputButton = QtWidgets.QPushButton('Select Input EXR Sequence')
        self.inputButton.clicked.connect(self.selectInputSequence)
        layout.addWidget(self.inputButton)
        
        # Codec selection
        self.codecLabel = QtWidgets.QLabel('Select Codec:')
        self.codecCombo = QtWidgets.QComboBox()
        self.codecCombo.addItems(['mp4', 'ProRes', 'Animation', 'H.265'])
        layout.addWidget(self.codecLabel)
        layout.addWidget(self.codecCombo)
        
        # Frame rate selection
        self.fpsLabel = QtWidgets.QLabel('Frame Rate (FPS):')
        self.fpsInput = QtWidgets.QLineEdit('24')
        layout.addWidget(self.fpsLabel)
        layout.addWidget(self.fpsInput)
        
        # Bitrate selection (optional)
        self.bitrateLabel = QtWidgets.QLabel('Bitrate (optional, e.g., 5M):')
        self.bitrateInput = QtWidgets.QLineEdit()  # Keep it optional
        layout.addWidget(self.bitrateLabel)
        layout.addWidget(self.bitrateInput)
        
        # Resolution selection
        self.resLabel = QtWidgets.QLabel('Output Resolution (e.g., 1920x1080):')
        self.resInput = QtWidgets.QLineEdit()
        layout.addWidget(self.resLabel)
        layout.addWidget(self.resInput)
        
        # Output file selection
        self.outputButton = QtWidgets.QPushButton('Select Output Location')
        self.outputButton.clicked.connect(self.selectOutputLocation)
        layout.addWidget(self.outputButton)
        
        self.outputPath = QtWidgets.QLineEdit()
        self.outputPath.setPlaceholderText('Output file path (optional)')
        layout.addWidget(self.outputPath)
        
        # Convert button
        self.convertButton = QtWidgets.QPushButton('Convert')
        self.convertButton.clicked.connect(self.convertSequence)
        layout.addWidget(self.convertButton)
        
        self.setLayout(layout)
        self.show()
    
    def selectInputSequence(self):
        options = QtWidgets.QFileDialog.Options()
        fileName, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Select First EXR File', '', 'EXR Files (*.exr)', options=options)
        if fileName:
            self.inputDirectory = os.path.dirname(fileName)
            baseName = os.path.basename(fileName)
            prefix = ''.join(filter(lambda x: not x.isdigit(), baseName))
            pattern = prefix + '*[0-9]*.exr'
            self.sequenceFiles = sorted(glob.glob(os.path.join(self.inputDirectory, pattern)))
            QtWidgets.QMessageBox.information(self, 'Sequence Selected', f'Found {len(self.sequenceFiles)} files in sequence.')
    
    def selectOutputLocation(self):
        options = QtWidgets.QFileDialog.Options()
        fileName, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Select Output Location', '', 'All Files (*)', options=options)
        if fileName:
            self.outputPath.setText(fileName)
    
    def convertSequence(self):
        if not self.sequenceFiles:
            QtWidgets.QMessageBox.warning(self, 'No Sequence', 'Please select an input EXR sequence.')
            return
        
        outputCodec = self.codecCombo.currentText()
        fps = self.fpsInput.text()
        bitrate = self.bitrateInput.text() if self.bitrateInput.text() else None
        resolution = self.resInput.text().strip()

        # Validate FPS
        if not fps.isdigit():
            QtWidgets.QMessageBox.warning(self, 'Invalid FPS', 'Please enter a valid frame rate (FPS).')
            return

        # Validate Resolution Format if provided
        if resolution and 'x' not in resolution:
            QtWidgets.QMessageBox.warning(self, 'Invalid Resolution', 'Please enter resolution in WIDTHxHEIGHT format (e.g., 1920x1080).')
            return
        
        # Determine output file path
        if self.outputPath.text():
            outputFile = self.outputPath.text()
        else:
            outputFile = os.path.join(self.inputDirectory, f'output.{outputCodec.lower()}')
        
        # Ensure the output file has the correct extension
        if not outputFile.lower().endswith(f'.{outputCodec.lower()}'):
            outputFile += f'.{outputCodec.lower()}'
        
        # Build FFmpeg command
        inputPath = os.path.join(self.inputDirectory, '%*.exr')
        
        cmd = ['ffmpeg', '-framerate', fps, '-i', inputPath]
        
        if resolution:
            cmd.extend(['-s', resolution])
        if bitrate:
            cmd.extend(['-b:v', bitrate])
        
        # Codec-specific settings
        if outputCodec == 'mp4':
            cmd.extend(['-c:v', 'libx264', '-pix_fmt', 'yuv420p'])
        elif outputCodec == 'ProRes':
            cmd.extend(['-c:v', 'prores_ks'])
        elif outputCodec == 'Animation':
            cmd.extend(['-c:v', 'qtrle'])
        elif outputCodec == 'H.265':
            cmd.extend(['-c:v', 'libx265'])
        
        cmd.append(outputFile)
        
        try:
            # Execute FFmpeg command
            subprocess.run(cmd, check=True)
            QtWidgets.QMessageBox.information(self, 'Conversion Complete', f'Output file saved as {outputFile}.')
        except subprocess.CalledProcessError as e:
            QtWidgets.QMessageBox.critical(self, 'Conversion Failed', f'An error occurred during conversion:\n{e}')

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    converter = FFmpegConverter()
    sys.exit(app.exec_())
