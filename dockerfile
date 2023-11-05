FROM continuumio/miniconda3

WORKDIR /app


# Create the environment
COPY requirements.yml .
RUN conda env create -f requirements.yml

# Activate the environment, and make sure it's activated:
SHELL ["conda", "run", "-n", "thingy", "/bin/bash", "-c"]
RUN echo "Make sure requirements are installed:"
RUN python -c "import requests"
RUN python -c "import py7zr"

COPY thingy_grabber.py .
ENTRYPOINT ["conda", "run", "-n", "thingy", "python", "thingy_grabber.py"]