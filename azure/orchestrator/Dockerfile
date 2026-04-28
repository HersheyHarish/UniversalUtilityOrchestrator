# To enable ssh & remote debugging on app service change the base image to the one below
# FROM mcr.microsoft.com/azure-functions/python:4-python3.11-appservice
FROM mcr.microsoft.com/azure-functions/python:4-python3.11

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true

# Copy requirements and install
COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt

# Copy all application files to the webroot
COPY . /home/site/wwwroot
