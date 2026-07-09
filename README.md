# DashboardBZA

Dashboard Django para gestion de personal, accesos, visitantes, vehiculos y consultas internas.

## Estado actual

- Aplicacion desplegada en la VM de Vultr en `https://bonanza.robio-ai.com`
- `nginx` funcionando como reverse proxy
- `gunicorn` sirviendo Django en `127.0.0.1:8000`
- SSL emitido con `certbot`
- Logo activo en la barra superior, favicon y pantalla de login
- Endpoint de placas disponible
- Endpoint de personas disponible

## Estructura

- `inventario_bonanza/manage.py`: entrada de comandos de Django
- `inventario_bonanza/inventario_bonanza/`: configuracion principal del proyecto
- `inventario_bonanza/gestion_personal/`: app principal
- `inventario_bonanza/static/`: estaticos fuente versionables
- `inventario_bonanza/media/`: archivos subidos localmente
- `inventario_bonanza/staticfiles/`: salida de `collectstatic`
- `consulta_people/`: fuentes de consulta para personas
- `consulta_plates/`: fuentes de consulta para placas

## Flujo de despliegue

En la VM actual el proyecto vive en:

```bash
/root/bonanza
```

Servicios del sistema:

- `bonanza-gunicorn.service`
- `nginx.service`

Ruta de la configuracion de sitio:

- `/etc/nginx/sites-available/bonanza`

Certificado SSL:

- `/etc/letsencrypt/live/bonanza.robio-ai.com/`

## Configuracion local

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python inventario_bonanza/manage.py migrate
venv/bin/python inventario_bonanza/manage.py runserver
```

## Configuracion de produccion en la VM

```bash
cd /root/bonanza
/root/bonanza/venv/bin/python inventario_bonanza/manage.py migrate --noinput
/root/bonanza/venv/bin/python inventario_bonanza/manage.py collectstatic --noinput
systemctl restart bonanza-gunicorn
systemctl restart nginx
```

## Variables de entorno

### Django

- `DJANGO_SECRET_KEY`
- `DEBUG`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `APP_URL`

### Base de datos

- `DATABASE_ENGINE`
- `DATABASE_NAME`
- `DATABASE_ADMIN_USER`
- `DATABASE_ADMIN_PASSWORD`
- `DATABASE_DESCRIPTION`

### Administrador global

- `GLOBAL_ADMIN_USERNAME`
- `GLOBAL_ADMIN_PASSWORD`
- `GLOBAL_ADMIN_EMAIL`

### MinIO / S3

- `MINIO_ROOT_USER`
- `MINIO_ROOT_PASSWORD`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET_NAME`
- `MINIO_ENDPOINT_URL`
- `MINIO_CONSOLE_URL`
- `MINIO_VOLUMES`
- `MINIO_OPTS`
- `MINIO_PERSON_PHOTO_PATH`

### API de consultas

- `PLATE_LOOKUP_API_TOKEN`
- `PERSON_LOOKUP_API_TOKEN`

### Telegram

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_IDS`

### Correo

- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_USE_TLS`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`

### Servicios locales

- `DJANGO_SERVICE`
- `MINIO_SERVICE`
- `NGINX_SITE`

## Endpoints web principales

- `/login/`
- `/logout/`
- `/role_redirect/`
- `/global/dashboard/`
- `/global/placas/`
- `/global/consultas-personas/`
- `/server/`
- `/server/api/`

## API de placas

### URL

```text
GET /api/plate-lookup/<placa>/
```

### Autenticacion

Si `PLATE_LOOKUP_API_TOKEN` tiene valor, se debe enviar:

```text
X-Plate-Lookup-Token: <token>
```

### Ejemplo

```bash
curl -H "X-Plate-Lookup-Token: <token>" \
  https://bonanza.robio-ai.com/api/plate-lookup/ABC1234/
```

### Respuesta

Devuelve un JSON con:

- `ok`
- `record`
- `error` cuando aplica

La estructura de `record` incluye:

- `placa`
- `estado`
- `propietario`
- `marca`
- `modelo`
- `anio`
- `clase`
- `tipo`
- `servicio`
- `uso`
- `vin`
- `motor`
- `source_errors`
- `normalized_data`

### Comportamiento

- Si no existe el registro, se crea en estado `pending`
- La consulta se procesa en segundo plano
- Si faltan credenciales externas, la respuesta puede traer errores por fuente

## API de personas

### URL

```text
GET /api/person-lookup/<cedula>/
```

### Autenticacion

Si `PERSON_LOOKUP_API_TOKEN` tiene valor, se debe enviar:

```text
X-Person-Lookup-Token: <token>
```

### Ejemplo

```bash
curl -H "X-Person-Lookup-Token: <token>" \
  https://bonanza.robio-ai.com/api/person-lookup/0102030405/
```

### Respuesta

Devuelve un JSON con:

- `ok`
- `record`
- `error` cuando aplica

La estructura de `record` incluye:

- `cedula`
- `estado`
- `nombre_completo`
- `procesos_actor_total`
- `procesos_demandado_total`
- `citaciones_total`
- `normalized_data`
- `source_errors`

### Comportamiento

- Si no existe el registro, se crea en estado `pending`
- La consulta se procesa en segundo plano
- Las fuentes que requieren captcha o navegador pueden reportar error parcial

## API de estado del servidor

### URL

```text
GET /server/api/
```

### Acceso

- Requiere sesion autenticada
- El acceso en la interfaz web esta restringido a `global_admin`

### Incluye

- host
- uptime
- cpu
- memoria
- discos
- base de datos
- procesos de consulta
- colas de placas y personas

## MinIO y archivos

- Las fotos y archivos privados se sirven a traves de MinIO
- La ruta de media privada usa `private_media`
- `collectstatic` publica el contenido de `inventario_bonanza/static/`

## Branding

- Logo principal: `inventario_bonanza/static/img/logo.png`
- Favicon: el mismo logo
- Login con cabecera visual del proyecto

## Pendientes

- `www.bonanza.robio-ai.com` no tiene DNS activo aun
- Si se quiere usar `www`, hay que crear el A record y volver a emitir el certificado
- Revisar si se desea cambiar SQLite por PostgreSQL para produccion
- Confirmar si MinIO sera local definitivo o migrado a otro almacenamiento
- Definir si los tokens de API se consumiran solo internamente o desde sistemas externos

## Comandos utiles

Ver estado de servicios:

```bash
systemctl status bonanza-gunicorn
systemctl status nginx
```

Ver logs:

```bash
journalctl -u bonanza-gunicorn -f
journalctl -u nginx -f
tail -f logs/django.log
```

Verificacion rapida:

```bash
python3 inventario_bonanza/manage.py check
```
