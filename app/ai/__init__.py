"""AI gateway: the only place that knows which LLM / embedding provider is in use.

Feature modules ask for a chat model or embedder *by task* and never import a provider SDK. Switching from
DeepSeek to OpenAI, Anthropic or a local Ollama is an environment change (see core/config.py), not a code change.
"""
