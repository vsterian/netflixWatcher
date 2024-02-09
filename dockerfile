# Use a light Windows base image
FROM mcr.microsoft.com/windows:1809

# Set the working directory
WORKDIR /app


# Step 1: Install Python
COPY Setup/installpython.ps1 C:/Setup/
RUN powershell -Command "Set-ExecutionPolicy Unrestricted -Scope Process; C:/Setup/installpython.ps1"
RUN powershell -Command "python.exe -m pip install --upgrade pip"

# Step 2: Install Chrome
COPY Setup/installchrome.ps1 C:/Setup/
RUN powershell -Command "Set-ExecutionPolicy Unrestricted -Scope Process; C:/Setup/installchrome.ps1"

# Step 3: Copy the requirements.txt file and install the Python libraries
COPY app/requirements.txt .

# Install Python libraries
RUN pip install -r requirements.txt

# Copy the application files
COPY app/ .

# Start the main script when the container starts
CMD ["python", "application.py"]

