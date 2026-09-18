# Personalize your assistant

Whisp can judge an email using your context and preferences instead of producing the
same generic summary for everyone. Its assistant profile controls how it speaks, which
language it uses, and what it treats as important.

## Create your profile

Copy the example profile:

```bash
cp config/assistant.example.toml config/assistant.toml
```

Whisp loads `config/assistant.toml` by default. The personal file is ignored by Git,
while the example remains safe to share with the project.

## Profile settings

Edit the `[assistant]` table:

```toml
[assistant]
personality = "Warm, direct, and proactive."
default_language = "Vietnamese"
response_style = "Use two short paragraphs and finish with the next action."

user_context = """
I lead a small software team. I care about customer problems, delivery blockers,
security, and anything that needs my approval.
"""

priorities = [
  "Customer incidents",
  "Requests blocking my team",
  "Deadlines within seven days",
]

custom_instructions = "Keep technical terms in English and flag suspicious requests."
```

- `personality` controls tone and attitude.
- `default_language` controls the language of every notification.
- `response_style` controls length, structure, and level of detail.
- `user_context` helps Whisp decide why a message matters to you.
- `priorities` identifies topics that deserve attention.
- `custom_instructions` holds any remaining preferences specific to your workflow.

The profile is sent to the configured AI model with each email. Do not include passwords,
API keys, or other secrets in it.

## Use another path

Set the path in `.env` when you keep the profile elsewhere:

```env
WHISP_ASSISTANT_PROFILE_PATH=/path/to/assistant.toml
```

When the file does not exist, Whisp uses a concise English assistant profile so existing
installations continue to work.

## Apply changes

Restart the running Whisp process after editing the profile. Then send yourself a test
email or process a new message to see the updated behavior.
