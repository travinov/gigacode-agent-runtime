---
name: runtime-all-fields-example
description: TEST EXAMPLE. Demonstrates every GigaCode Skill metadata field supported by Runtime Configuration Studio.
priority: 50
paths:
  - "**/*.md"
  - "**/*.yaml"
  - "**/*.json"
user-invocable: true
disable-model-invocation: true
---

# Runtime All Fields Example

Use this Skill only for the bundled `corporate-all-fields-example` acceptance
scenario or for manually inspecting a complete Skill in Runtime Configuration
Studio.

1. Read only the text supplied in the prompt.
2. Do not call tools, read workspace files, or make network requests.
3. Return a JSON result matching the step output schema.
4. Add `"skill_example": "RUNTIME_ALL_FIELDS_SKILL_OK"` to the result.

The `disable-model-invocation` flag intentionally prevents native automatic
selection. Runtime can still assign this Skill explicitly through `skill_refs`.
