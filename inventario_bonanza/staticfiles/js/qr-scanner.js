(function () {
  'use strict';

  const resultContainer = document.getElementById('qr-result');
  const cameraStatusAlert = document.getElementById('camera-status-alert');
  const cameraStatusText = document.getElementById('camera-status-text');
  const cameraIndicator = document.getElementById('camera-indicator');
  const startButton = document.getElementById('start-scan-button');
  const stopButton = document.getElementById('stop-scan-button');
  const cameraSelectContainer = document.getElementById('camera-select-container');
  const cameraSelect = document.getElementById('camera-select');
  const facingModeContainer = document.getElementById('facing-mode-container');
  const torchContainer = document.getElementById('torch-container');
  const torchButton = document.getElementById('torch-button');
  const manualCedulaInput = document.getElementById('manual-cedula');
  const manualCedulaButton = document.getElementById('process-manual-cedula');

  let html5QrcodeScanner = null;
  let cameras = [];
  let currentCameraId = null;
  let torchOn = false;

  function logStatus(message, type = 'info') {
    if (!cameraStatusAlert || !cameraStatusText) return;
    cameraStatusText.textContent = message;
    cameraStatusAlert.className = `alert alert-${type} mb-3`;
    cameraStatusAlert.style.display = 'block';
  }

  function setCameraIndicator(active) {
    if (!cameraIndicator) return;
    cameraIndicator.textContent = active ? 'Activo' : 'Inactivo';
    cameraIndicator.className = active ? 'badge bg-success' : 'badge bg-warning';
  }

  function showCameraSelect(deviceList) {
    if (!cameraSelectContainer || !cameraSelect) return;
    cameraSelect.innerHTML = '<option value="">Seleccionar cámara</option>';
    deviceList.forEach(device => {
      const option = document.createElement('option');
      option.value = device.id;
      option.textContent = device.label || `Cámara ${cameraSelect.options.length}`;
      cameraSelect.appendChild(option);
    });
    cameraSelectContainer.style.display = deviceList.length > 1 ? 'block' : 'none';
  }

  function getSelectedCameraId() {
    if (cameraSelect && cameraSelect.value) {
      return cameraSelect.value;
    }
    return currentCameraId;
  }

  function getFacingMode() {
    if (!facingModeContainer) return 'auto';
    const selectedRadio = facingModeContainer.querySelector('input[name="facing-mode"]:checked');
    return selectedRadio ? selectedRadio.value : 'auto';
  }

  function displayResult(message, success = true) {
    if (!resultContainer) return;
    resultContainer.innerHTML = `
      <div class="alert alert-${success ? 'success' : 'danger'}">
        <strong>${success ? 'Escaneo exitoso:' : 'Error:'}</strong> ${message}
      </div>`;
  }

  async function setupCameraList() {
    if (typeof Html5Qrcode === 'undefined') {
      logStatus('La librería de escaneo no está cargada.', 'danger');
      setCameraIndicator(false);
      setTorchVisibility(false);
      return;
    }

    try {
      const devices = await Html5Qrcode.getCameras();
      if (!devices || devices.length === 0) {
        logStatus('No se encontraron cámaras disponibles.', 'warning');
        setCameraIndicator(false);
        setTorchVisibility(false);
        return;
      }

      cameras = devices.map(device => ({ id: device.id, label: device.label }));
      currentCameraId = cameras[0].id;
      showCameraSelect(cameras);
      setCameraIndicator(false);
      logStatus('Cámaras detectadas. Seleccione una cámara e inicie el escáner.', 'info');
      setTorchVisibility(false);
    } catch (error) {
      console.error(error);
      logStatus('No se pudo acceder a la cámara. Verifique permisos del navegador.', 'danger');
      setCameraIndicator(false);
      setTorchVisibility(false);
    }
  }

  async function startScanner() {
    if (typeof Html5Qrcode === 'undefined') {
      displayResult('La librería html5-qrcode no está disponible.', false);
      return;
    }

    const selectedCameraId = getSelectedCameraId();
    if (!selectedCameraId) {
      displayResult('Seleccione una cámara antes de iniciar el escáner.', false);
      return;
    }

    if (!html5QrcodeScanner) {
      html5QrcodeScanner = new Html5Qrcode('reader', { verbose: false });
    }

    const config = {
      fps: 10,
      qrbox: { width: 250, height: 250 },
      aspectRatio: 1.0,
      disableFlip: false,
      experimentalFeatures: { useBarCodeDetectorIfSupported: true }
    };

    try {
      await html5QrcodeScanner.start(
        { deviceId: { exact: selectedCameraId } },
        config,
        handleScanSuccess,
        handleScanError
      );

      startButton.disabled = true;
      stopButton.disabled = false;
      stopButton.style.display = 'inline-block';
      setCameraIndicator(true);
      logStatus('Escáner activo. Apunte el QR a la cámara.', 'success');

      const stream = html5QrcodeScanner._oMediaStream;
      const supportsTorch = stream?.getVideoTracks?.()?.[0]?.getCapabilities?.()?.torch;
      setTorchVisibility(!!supportsTorch);
    } catch (error) {
      console.error('Error al iniciar el escáner:', error);
      logStatus('No se pudo iniciar el escáner. Verifique los permisos de la cámara.', 'danger');
      setCameraIndicator(false);
      displayResult('Error al iniciar el escáner. ' + (error.message || error), false);
    }
  }

  async function stopScanner() {
    if (!html5QrcodeScanner) return;

    try {
      await html5QrcodeScanner.stop();
      await html5QrcodeScanner.clear();
    } catch (error) {
      console.warn('Error deteniendo el escáner:', error);
    }

    html5QrcodeScanner = null;
    startButton.disabled = false;
    stopButton.disabled = true;
    stopButton.style.display = 'none';
    setCameraIndicator(false);
    setTorchVisibility(false);
    torchOn = false;
    if (torchButton) {
      torchButton.innerHTML = '<i class="fas fa-lightbulb me-1"></i>Encender Linterna';
    }
    logStatus('Escáner detenido.', 'info');
  }

  function handleScanSuccess(decodedText) {
    displayResult(decodedText, true);
    if (manualCedulaInput) {
      manualCedulaInput.value = decodedText;
    }
    if (document.getElementById('cedula-auto')) {
      document.getElementById('cedula-auto').value = decodedText;
    }
    processCedula(decodedText);
  }

  function handleScanError(errorMessage) {
    if (!errorMessage) return;
    console.debug('Escaneo:', errorMessage);
  }

  function setTorchVisibility(visible) {
    if (!torchContainer) return;
    torchContainer.style.display = visible ? 'block' : 'none';
  }

  async function toggleTorch() {
    if (!html5QrcodeScanner) return;
    const stream = html5QrcodeScanner._oMediaStream;
    if (!stream) return;

    const videoTrack = stream.getVideoTracks?.()[0];
    if (!videoTrack) return;

    const capabilities = videoTrack.getCapabilities?.();
    if (!capabilities?.torch) {
      displayResult('La linterna no está disponible para esta cámara.', false);
      return;
    }

    try {
      torchOn = !torchOn;
      await videoTrack.applyConstraints({ advanced: [{ torch: torchOn }] });
      torchButton.innerHTML = torchOn
        ? '<i class="fas fa-lightbulb me-1"></i>Apagar Linterna'
        : '<i class="fas fa-lightbulb me-1"></i>Encender Linterna';
    } catch (error) {
      console.error('Error al alternar linterna:', error);
      displayResult('No se pudo cambiar el estado de la linterna.', false);
    }
  }

  function processCedula(cedula) {
    if (!cedula || !cedula.trim()) return;
    const formattedCedula = cedula.trim();
    const autoForm = document.getElementById('formMarcacionAuto');
    const quickForm = document.getElementById('formMarcacionRapida');

    if (autoForm) {
      submitAutoCedula(formattedCedula);
      return;
    }

    if (quickForm) {
      const cedulaRapida = document.getElementById('cedula-rapida');
      if (cedulaRapida) {
        cedulaRapida.value = formattedCedula;
      }
      displayResult('Cédula detectada y colocada en el formulario.', true);
    }
  }

  function submitAutoCedula(cedula) {
    const motivo = document.getElementById('motivo-auto') ? document.getElementById('motivo-auto').value : '';
    let resultadoDiv = document.getElementById('resultado-marcacion-auto');
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;

    if (!csrfToken) {
      displayResult('No se encontró token CSRF. Recargue la página.', false);
      return;
    }

    if (!resultadoDiv && resultContainer) {
      resultadoDiv = resultContainer;
    }

    if (resultadoDiv) {
      resultadoDiv.innerHTML = '<div class="alert alert-info">Procesando...</div>';
    }

    fetch('/operador/marcacion-rapida/', {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken,
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: `cedula=${encodeURIComponent(cedula)}&tipo=auto&motivo=${encodeURIComponent(motivo)}`
    })
      .then(response => response.json())
      .then(data => {
        if (data.status === 'ok') {
          const iconClass = data.tipo === 'entrada' ? 'fa-sign-in-alt' : 'fa-sign-out-alt';
          const tipoTexto = data.tipo === 'entrada' ? 'Entrada' : 'Salida';
          const bgColor = data.tipo === 'entrada' ? 'success' : 'danger';
          if (resultadoDiv) {
            resultadoDiv.innerHTML = `
              <div class="alert alert-${bgColor}">
                <div class="d-flex align-items-center">
                  <div class="me-3">
                    <i class="fas ${iconClass} fa-2x"></i>
                  </div>
                  <div>
                    <strong>${data.message}</strong><br>
                    <span>Tipo: ${tipoTexto}</span>
                  </div>
                </div>
              </div>`;
          }
          setTimeout(() => {
            const modal = bootstrap.Modal.getInstance(document.getElementById('modalQR'));
            if (modal) modal.hide();
            stopScanner();
          }, 1400);
        } else {
          if (resultadoDiv) {
            resultadoDiv.innerHTML = `
              <div class="alert alert-danger">
                <strong>Error:</strong> ${data.error}
              </div>`;
          }
        }
      })
      .catch(error => {
        console.error('Error en marcación automática:', error);
        if (resultadoDiv) {
          resultadoDiv.innerHTML = `
            <div class="alert alert-danger">
              <strong>Error:</strong> Ocurrió un problema al procesar la solicitud.
            </div>`;
        }
      });
  }

  document.addEventListener('DOMContentLoaded', async function () {
    await setupCameraList();

    if (startButton) {
      startButton.addEventListener('click', function () {
        startScanner();
      });
    }

    if (stopButton) {
      stopButton.addEventListener('click', function () {
        stopScanner();
      });
    }

    if (cameraSelect) {
      cameraSelect.addEventListener('change', function () {
        currentCameraId = cameraSelect.value || currentCameraId;
      });
    }

    if (torchButton) {
      torchButton.addEventListener('click', function () {
        toggleTorch();
      });
    }

    if (manualCedulaButton && manualCedulaInput) {
      manualCedulaButton.addEventListener('click', function () {
        processCedula(manualCedulaInput.value);
      });
    }

    if (manualCedulaInput) {
      manualCedulaInput.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') {
          event.preventDefault();
          processCedula(manualCedulaInput.value);
        }
      });
    }

    const modalQR = document.getElementById('modalQR');
    if (modalQR) {
      modalQR.addEventListener('hidden.bs.modal', function () {
        stopScanner();
      });
    }

    document.addEventListener('keydown', function (event) {
      if (!document.getElementById('modalQR')?.classList.contains('show')) return;
      if (event.key === 'Enter') {
        return;
      }
    });
  });

    if (typeof window !== 'undefined') {
      window.processCedula = processCedula;
      window.procesarCedula = processCedula;
    }
  })();
