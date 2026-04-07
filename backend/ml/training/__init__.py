"""Training data generators for Agentop agent fine-tuning (LoRA/QLoRA).

Generators produce gold datasets in ShareGPT JSONL format for:
  - prompt_engineer: messy→structured prompt pairs
  - education_agent: student question→scaffolded response
  - higgsfield_agent: creative goal→platform-ready spec
"""
