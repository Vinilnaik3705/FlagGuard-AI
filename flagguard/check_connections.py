import os
from dotenv import load_dotenv
from .providers import sdk_flags, management_environment, groq_models, explain, ProviderError

def verify_model():
    model = os.getenv("LLM_MODEL","openai/gpt-oss-20b")
    if model not in {item["id"] for item in groq_models().get("data",[])}:
        raise ProviderError("Configured model unavailable")

def main():
    load_dotenv()
    checks = [
        ("Flagsmith SDK", sdk_flags),
        ("Flagsmith Management API (read only)", management_environment),
        ("Groq model availability", verify_model),
        ("Groq inference", lambda: explain({"recommendation":"monitor","groups":{}})),
    ]
    ok = True
    for label, fn in checks:
        try:
            fn()
            print(f"PASS: {label}")
        except ProviderError as exc:
            print(f"FAIL: {label}: {exc}")
            ok = False
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
