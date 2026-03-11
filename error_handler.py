"""
P0优化：网络错误处理和重试机制
- 错误分类和处理策略
- 统一的重试装饰器
- 自定义异常类
"""
import time
import logging
from functools import wraps
from typing import Callable, Optional, Type, Tuple
import requests

logger = logging.getLogger(__name__)


# ========== 自定义异常类 ==========

class TradingError(Exception):
    """交易相关错误基类"""
    pass


class APIError(TradingError):
    """API调用错误"""
    def __init__(self, message: str, code: int = None, endpoint: str = None):
        super().__init__(message)
        self.code = code
        self.endpoint = endpoint


class NetworkError(APIError):
    """网络错误（可重试）"""
    pass


class RateLimitError(APIError):
    """速率限制错误（可重试）"""
    pass


class InsufficientBalanceError(TradingError):
    """余额不足"""
    pass


class OrderExecutionError(TradingError):
    """订单执行错误"""
    def __init__(self, message: str, order_id: str = None, symbol: str = None):
        super().__init__(message)
        self.order_id = order_id
        self.symbol = symbol


class DataError(TradingError):
    """数据错误"""
    pass


# ========== 错误分类 ==========

class ErrorClassifier:
    """错误分类器"""
    
    # 可重试的错误码（临时错误）
    RETRYABLE_CODES = {
        # 网络错误
        1003,  # 网络问题
        -1021,  # 时间戳错误
        -1003,  # 请求超时
        
        # 速率限制
        429,  # Too Many Requests
        418,  # IP被限制
    }
    
    # 永久错误码（不重试）
    PERMANENT_CODES = {
        -2010,  # 余额不足
        -2011,  # 订单被拒绝
        -2019,  # 杠杆设置失败
        -4001,  # 无效参数
        -4002,  # 无效请求
    }
    
    @classmethod
    def classify_error(cls, error: Exception, error_code: int = None) -> Tuple[Type[Exception], bool]:
        """
        分类错误
        
        Returns:
            (error_class, is_retryable): 错误类和是否可重试
        """
        # 网络错误
        if isinstance(error, (requests.ConnectionError, requests.Timeout)):
            return NetworkError, True
        
        # 速率限制
        if isinstance(error, requests.HTTPError):
            if hasattr(error, 'response') and error.response.status_code == 429:
                return RateLimitError, True
            if hasattr(error, 'response') and error.response.status_code == 418:
                return RateLimitError, True
        
        # API错误码分类
        if error_code is not None:
            if error_code in cls.RETRYABLE_CODES:
                return NetworkError, True
            elif error_code in cls.PERMANENT_CODES:
                if error_code == -2010:
                    return InsufficientBalanceError, False
                elif error_code == -2011:
                    return OrderExecutionError, False
                else:
                    return APIError, False
        
        # 默认：可重试的网络错误
        return NetworkError, True


# ========== 重试装饰器 ==========

def retry_on_error(
    max_retries: int = 3,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None
):
    """
    重试装饰器
    
    Args:
        max_retries: 最大重试次数
        backoff: 退避倍数（指数退避）
        exceptions: 要捕获的异常类型
        on_retry: 重试时的回调函数
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    # 分类错误
                    error_code = getattr(e, 'code', None)
                    error_class, is_retryable = ErrorClassifier.classify_error(e, error_code)
                    
                    # 如果不可重试，直接抛出
                    if not is_retryable:
                        raise error_class(str(e)) from e
                    
                    # 如果已达到最大重试次数，抛出
                    if attempt >= max_retries - 1:
                        raise error_class(f"重试{max_retries}次后仍失败: {str(e)}") from e
                    
                    # 计算等待时间（指数退避）
                    wait_time = backoff ** attempt
                    
                    # 调用重试回调
                    if on_retry:
                        on_retry(attempt + 1, max_retries, wait_time, e)
                    else:
                        logger.warning(
                            f"⚠️ {func.__name__} 失败 (尝试 {attempt+1}/{max_retries}): {e}, "
                            f"{wait_time:.1f}秒后重试"
                        )
                    
                    time.sleep(wait_time)
            
            # 所有重试都失败
            raise last_exception
        
        return wrapper
    return decorator


def retry_on_network_error(max_retries: int = 3, backoff: float = 2.0):
    """网络错误重试装饰器"""
    return retry_on_error(
        max_retries=max_retries,
        backoff=backoff,
        exceptions=(NetworkError, RateLimitError, requests.ConnectionError, requests.Timeout)
    )


# ========== 使用示例 ==========

if __name__ == "__main__":
    # 示例：使用重试装饰器
    @retry_on_network_error(max_retries=3)
    def example_api_call():
        response = requests.get("https://api.example.com/data", timeout=5)
        response.raise_for_status()
        return response.json()
    
    try:
        data = example_api_call()
        print(f"成功获取数据: {data}")
    except NetworkError as e:
        print(f"网络错误: {e}")
    except APIError as e:
        print(f"API错误: {e}")
