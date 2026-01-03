
import timeit
from pyaot.web.route.trie import RouteLearner

# Legacy implementation for comparison
def legacy_extract(path: str) -> str:
    parts = path.strip("/").split("/")
    template_parts = []
    for part in parts:
        if part.isdigit():
            template_parts.append("<id>")
        elif len(part) == 36 and part.count("-") == 4:
            template_parts.append("<uuid>")
        else:
            template_parts.append(part)
    return "/" + "/".join(template_parts)

def bench():
    learner = RouteLearner()
    paths = [
        "/users/123",
        "/api/v1/resource/uuid-1234-5678-90ab",
        "/static/file.css",
        "/users/456/posts/789"
    ]
    
    # Warmup
    for p in paths:
        learner.extract_and_learn(p)
        
    def run_legacy():
        for p in paths:
            legacy_extract(p)
            
    def run_learner():
        for p in paths:
            learner.extract_and_learn(p)
            
    t_legacy = timeit.timeit(run_legacy, number=100000)
    t_learner = timeit.timeit(run_learner, number=100000)
    
    print(f"Legacy: {t_legacy:.4f}s")
    print(f"Learner (Cached): {t_learner:.4f}s")
    print(f"Speedup: {t_legacy/t_learner:.2f}x")

if __name__ == "__main__":
    bench()
