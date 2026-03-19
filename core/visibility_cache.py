import time
from .raytracer import raytracer

class VisibilityCache:
    def __init__(self, timeout=0.3):
        self.cache = {}
        self.timeout = timeout

    def is_visible(self, start, end, pawn_addr):
        now = time.time()
        key = pawn_addr
        if key in self.cache:
            visible, timestamp = self.cache[key]
            if now - timestamp < self.timeout:
                return visible
        # Gọi ray tracer thật
        visible = raytracer.is_visible(start, end)
        self.cache[key] = (visible, now)
        return visible

    def clear(self):
        self.cache.clear()

# Instance dùng chung toàn chương trình
vis_cache = VisibilityCache()