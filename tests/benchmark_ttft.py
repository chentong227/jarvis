import time
import sys
import os
import random
import statistics
from pathlib import Path

os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"

# [P0+19-deps] 从 .env 加载 keys，绝不硬编码
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jarvis_config.keys import load_keys
_keys = load_keys()
GEMINI_KEY = _keys.GEMINI
OPENROUTER_KEY = _keys.OPENROUTER_MAIN

def generate_filler_text(size: int) -> str:
    base_text = """Sir, I understand you're testing the response performance of different LLM configurations. This is a comprehensive benchmark to evaluate the time-to-first-token across various providers and models. The goal is to determine which combination offers the best latency characteristics for your Jarvis implementation.
    
"""
    filler = "This is filler text to reach the desired prompt size. "
    while len(base_text) < size:
        base_text += filler
    return base_text[:size]

def test_google_genai(prompt: str, model: str, api_key: str) -> float:
    try:
        from google import genai
        import httpx
        
        client = genai.Client(
            api_key=api_key,
            http_options={'httpx_client': httpx.Client(proxy='http://127.0.0.1:7890', timeout=120.0)}
        )
        
        start = time.time()
        response = client.models.generate_content_stream(
            model=model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}]
        )
        
        for chunk in response:
            first_token_time = time.time() - start
            return first_token_time
            
        return time.time() - start
    except Exception as e:
        print(f"❌ Google {model} failed: {str(e)[:100]}", file=sys.stderr)
        return None

def test_openrouter(prompt: str, model: str, api_key: str) -> float:
    try:
        from openai import OpenAI
        
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis"},
            timeout=120.0
        )
        
        start = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        
        for chunk in response:
            if chunk.choices[0].delta.content and chunk.choices[0].delta.content.strip():
                first_token_time = time.time() - start
                return first_token_time
                
        return time.time() - start
    except Exception as e:
        print(f"❌ OpenRouter {model} failed: {str(e)[:100]}", file=sys.stderr)
        return None

def run_benchmark():
    sizes = [13000, 15000]
    providers = ['Google', 'OpenRouter']
    models = {
        'Google': ['gemini-3-flash-preview', 'gemini-2.5-flash'],
        'OpenRouter': ['google/gemini-3-flash-preview', 'google/gemini-2.5-flash']
    }
    runs_per_test = 5
    
    results = {}
    
    for size in sizes:
        print(f"\n{'='*70}", file=sys.stderr)
        print(f"📏 Prompt Size: {size:,} characters", file=sys.stderr)
        print(f"{'='*70}", file=sys.stderr)
        
        prompt = generate_filler_text(size)
        
        for provider in providers:
            for model in models[provider]:
                key = f"{size}_{provider}_{model.split('/')[-1]}"
                results[key] = []
                
                print(f"\n🔄 {provider} {model}...", file=sys.stderr)
                
                for i in range(runs_per_test):
                    print(f"  Run {i+1}/{runs_per_test}...", end="", flush=True, file=sys.stderr)
                    
                    if provider == 'Google':
                        ttft = test_google_genai(prompt, model, GEMINI_KEY)
                    else:
                        ttft = test_openrouter(prompt, model, OPENROUTER_KEY)
                    
                    if ttft is not None:
                        results[key].append(ttft)
                        print(f" {ttft:.2f}s", file=sys.stderr)
                    else:
                        print(" FAILED", file=sys.stderr)
                    
                    if i < runs_per_test - 1:
                        time.sleep(2)
    
    return results

def print_report(results):
    print("\n\n" + "="*80)
    print("📊 BENCHMARK REPORT: Time-to-First-Token (TTFT)")
    print("="*80)
    
    sizes = [13000, 15000]
    
    for size in sizes:
        print(f"\n📏 Prompt Size: {size:,} chars")
        print("-" * 75)
        print(f"{'Provider':<12} {'Model':<25} {'Mean (s)':<10} {'Min (s)':<10} {'Max (s)':<10} {'Std':<8}")
        print("-" * 75)
        
        for provider in ['Google', 'OpenRouter']:
            for model_name in ['gemini-3-flash-preview', 'gemini-2.5-flash']:
                if provider == 'OpenRouter':
                    model = f"google/{model_name}"
                else:
                    model = model_name
                
                key = f"{size}_{provider}_{model_name}"
                if key in results and len(results[key]) >= 3:
                    times = results[key]
                    mean = statistics.mean(times)
                    min_t = min(times)
                    max_t = max(times)
                    std = statistics.stdev(times)
                    
                    print(f"{provider:<12} {model_name:<25} {mean:<10.2f} {min_t:<10.2f} {max_t:<10.2f} {std:<8.2f}")
    
    print("\n" + "="*80)
    print("📈 Analysis Summary")
    print("="*80)
    
    for size in sizes:
        print(f"\n📏 {size:,} chars:")
        
        for model_name in ['gemini-3-flash-preview', 'gemini-2.5-flash']:
            google_key = f"{size}_Google_{model_name}"
            or_key = f"{size}_OpenRouter_{model_name}"
            
            if google_key in results and or_key in results:
                google_times = results[google_key]
                or_times = results[or_key]
                
                if google_times and or_times:
                    google_mean = statistics.mean(google_times)
                    or_mean = statistics.mean(or_times)
                    
                    diff = google_mean - or_mean
                    pct_diff = (diff / google_mean) * 100
                    
                    if diff > 0:
                        print(f"  {model_name}: OpenRouter is {pct_diff:.1f}% faster ({or_mean:.2f}s vs {google_mean:.2f}s)")
                    else:
                        print(f"  {model_name}: Google is {abs(pct_diff):.1f}% faster ({google_mean:.2f}s vs {or_mean:.2f}s)")

if __name__ == "__main__":
    print("🚀 Starting benchmark...", file=sys.stderr)
    print("This will run 2 sizes × 2 providers × 2 models × 5 runs = 40 tests", file=sys.stderr)
    print("Estimated time: ~8-10 minutes\n", file=sys.stderr)
    
    results = run_benchmark()
    print_report(results)
    
    print("\n✅ Benchmark completed!", file=sys.stderr)