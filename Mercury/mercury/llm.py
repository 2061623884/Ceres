"""OpenAI 兼容客户端。首次 chat() 时才创建 SDK 客户端，离线测试不需要 API Key。"""

from openai import OpenAI

from mercury import config


class OpenAIChatClient:
    def __init__(self, settings=None):
        self._client = None
        self._model = None
        self._settings = settings

    def chat(self, messages, tools=None):
        if self._client is None:
            s = config.llm_settings() if self._settings is None else self._settings
            self._client = OpenAI(base_url=s["base_url"], api_key=s["api_key"],
                                  timeout=45 if self._settings is None else s["timeout"])
            self._model = s["model"]
        kwargs = {"model": self._model, "messages": messages, "temperature": 0.2}
        if self._settings is not None:
            kwargs["max_tokens"] = self._settings["max_output_tokens"]
        if tools is not None:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return self._client.chat.completions.create(**kwargs).choices[0].message
