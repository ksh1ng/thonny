class ProviderError(Exception):
    pass


class AuthenticationError(ProviderError):
    pass


class RateLimitError(ProviderError):
    pass


class RequestCancelled(ProviderError):
    pass
