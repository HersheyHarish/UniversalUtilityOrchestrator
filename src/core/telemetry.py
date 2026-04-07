import os
import logging
from azure.monitor.opentelemetry import configure_azure_monitor

def setup_telemetry():
    """
    Configure OpenTelemetry with Azure Monitor given a connection string.
    If no connection string is present, it will just use standard python logging locally.
    """
    # Configure basic logging first so our startup messages show up
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    conn_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if conn_string:
        try:
            configure_azure_monitor(connection_string=conn_string)
            logging.info("Azure Monitor OpenTelemetry configured successfully.")
        except Exception as e:
            logging.warning(f"Failed to configure Azure Monitor: {e}")
    else:
        logging.info("No APPLICATIONINSIGHTS_CONNECTION_STRING found. Continuing without Azure Monitor Telemetry.")

def get_tracer(name: str):
    from opentelemetry import trace
    return trace.get_tracer(name)
