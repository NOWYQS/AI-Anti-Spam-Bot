import json
from openai import AsyncOpenAI
from .base import BaseAI, SpamResult
from .prompts import TEXT_PROMPT, IMAGE_PROMPT

class OpenAIClient(BaseAI):
    """OpenAI / 兼容接口客户端"""

    def __init__(self, api_key: str, base_url: str, model: str):
        super().__init__(api_key, base_url, model)
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def check_text(self, user_info: str, message: str) -> SpamResult:
        prompt = TEXT_PROMPT.format(user_info=user_info, message=message)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}]
        )
        return self._parse_result(response.choices[0].message.content)

    async def check_image(self, user_info: str, image_base64: str) -> SpamResult:
        prompt = IMAGE_PROMPT.format(user_info=user_info)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_base64}}
                ]
            }]
        )
        return self._parse_result(response.choices[0].message.content)

    def _parse_result(self, content: str) -> SpamResult:
        try:
            data = json.loads(content)
            return SpamResult(
                is_spam=data.get("state", 0) == 1,
                score=data.get("spam_score", 0),
                reason=data.get("spam_reason", ""),
                mock_text=data.get("spam_mock_text", "")
            )
        except json.JSONDecodeError:
            return SpamResult(is_spam=False, score=0, reason="解析失败", mock_text="")
