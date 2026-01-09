import logging
import requests

logger = logging.getLogger(__name__)

class HomeAssistantClient:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get_state(self, entity_id):
        url = f"{self.base_url}/api/states/{entity_id}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"HA: Error fetching state for {entity_id} from HA: {e}")
            return None

    def call_service(self, domain, service, entity_id, **kwargs):
        url = f"{self.base_url}/api/services/{domain}/{service}"
        payload = {"entity_id": entity_id}
        if kwargs:
            payload.update(kwargs)
            
        logger.info(f"HA: Calling service {domain}.{service} for {entity_id} with data {kwargs}")
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=10)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"HA: Error calling service {domain}.{service}: {e}")
            return False
