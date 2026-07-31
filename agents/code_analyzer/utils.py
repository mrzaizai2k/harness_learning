import yaml
import time
import logging
import inspect
from functools import wraps

logger = logging.getLogger("utils")

def read_config(path = 'config/config.yaml'):
    with open(path, 'r') as file:
        data = yaml.safe_load(file)
    return data

def timeit(func):
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        execution_time = end_time - start_time
        logger.info("%s took %.2f seconds to execute.", func.__name__, execution_time)
        return result

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        end_time = time.time()
        execution_time = end_time - start_time
        logger.info("%s took %.2f seconds to execute.", func.__name__, execution_time)
        return result

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper
    
def extract_json(text: str) -> dict:
    start_index = text.find('{')
    end_index = text.rfind('}') + 1
    json_string = text[start_index:end_index]
    json_string = json_string.replace('true', 'True').replace('false', 'False').replace('null', 'None')
    result = eval(json_string)
    return result