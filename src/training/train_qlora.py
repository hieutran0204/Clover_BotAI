"""
name: train_qlora
description: QLoRA fine-tuning script optimized for 4GB VRAM NVIDIA RTX 3050 using 4-bit NF4 quantization on Qwen2.5-3B-Instruct.
"""

import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def train(
    dataset_path: Path,
    output_dir: Path,
    base_model_name: str = "Qwen/Qwen2.5-3B-Instruct",
    epochs: int = 3,
    lr: float = 2e-4,
) -> None:
    """
    Run 4-bit NF4 QLoRA fine-tuning on Qwen2.5-3B-Instruct within a strict 4GB VRAM envelope.

    Parameters:
        dataset_path (Path): Path to ChatML train.jsonl.
        output_dir (Path): Destination directory for LoRA adapter weights.
        base_model_name (str): Hugging Face model identifier.
        epochs (int): Number of training epochs.
        lr (float): Peak learning rate.
    """
    import torch
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from trl import SFTTrainer

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Starting QLoRA training on base model '{base_model_name}'...")
    print(f"VRAM Optimization: 4-bit NF4, Gradient Checkpointing, batch_size=1, accum=8")

    # 1. 4-bit Quantization Configuration (fits ~2.0 GB VRAM)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    # 2. Load Tokenizer & Model
    tokenizer = AutoTokenizer.from_pretrained(base_model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)
    model.gradient_checkpointing_enable()

    # 3. LoRA Adapter Configuration
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    # 4. Load ChatML JSONL Dataset
    dataset = load_dataset("json", data_files=str(dataset_path), split="train")

    def format_chatml(example):
        return {"text": tokenizer.apply_chat_template(example["messages"], tokenize=False)}

    formatted_dataset = dataset.map(format_chatml)

    # 5. Training Arguments (RTX 3050 4GB Guardrails)
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=lr,
        fp16=True,
        logging_steps=5,
        save_strategy="epoch",
        optim="paged_adamw_8bit",
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        report_to="none",
    )

    # 6. SFT Trainer
    trainer = SFTTrainer(
        model=model,
        train_dataset=formatted_dataset,
        dataset_text_field="text",
        max_seq_length=1024,
        tokenizer=tokenizer,
        args=training_args,
    )

    trainer.train()
    trainer.model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    print(f"LoRA adapter successfully saved to: {output_dir}")


def main() -> None:
    """CLI entrypoint for QLoRA training."""
    parser = argparse.ArgumentParser(description="QLoRA training on 4GB VRAM GPU.")
    parser.add_argument("--data", type=Path, default=Path("datasets/train.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("models/english-tutor-lora"))
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args()
    train(dataset_path=args.data, output_dir=args.out, epochs=args.epochs)


if __name__ == "__main__":
    main()

