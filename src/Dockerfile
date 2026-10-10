# Imagen de contenedor: el modelo (~176 MB) + dependencias superan el límite de 250 MB del zip
FROM public.ecr.aws/lambda/python:3.12

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Modelo de segmentación u2net (se descarga en el build, no se versiona en git)
ENV U2NET_MODEL=/opt/models/u2net.onnx
RUN mkdir -p /opt/models && python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx', '/opt/models/u2net.onnx')"

COPY image_processor ${LAMBDA_TASK_ROOT}/image_processor

CMD ["image_processor.handler.lambda_handler"]
