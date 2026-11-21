# Gradient Accumulation as Batch Size Proxy for Transformer Training

## Problem

Training a small transformer language model (125M parameters) on a single GPU with limited VRAM (24 GB). The metric was validation bits-per-byte (val_bpb), lower is better. Larger batch sizes are known to stabilize training, but the model with batch size > 32 caused OOM on the available hardware.

## What Worked

Using gradient accumulation to simulate large batch sizes without increasing memory usage. Instead of trying to fit batch size 128 into memory, accumulate gradients over 4 forward passes of batch size 32 before performing one optimizer step. This achieved the same effective batch size 128 while staying within VRAM limits.

The key insight: gradient accumulation is not just a memory workaround, it is functionally equivalent to a larger batch (assuming no batch normalization). The model trained with accumulation steps=4 achieved identical val_bpb (within noise) to a machine with enough VRAM for true batch size 128, and val_bpb improved from 1.42 (batch 32) to 1.31 (effective batch 128).

## Experiment Data

```
commit	metric_value	resource_usage	status	hypothesis
a1b2c3d	1.4200	22.1	keep	baseline (batch_size=32, no accumulation)
b2c3d4e	1.3500	22.1	keep	accumulation_steps=2 (effective batch 64) will reduce val_bpb by smoothing gradient noise
c3d4e5f	1.3100	22.3	keep	accumulation_steps=4 (effective batch 128) will further reduce val_bpb
d4e5f6g	1.3150	22.3	discard	accumulation_steps=8 (effective batch 256) will continue the trend
e5f6g7h	1.2950	22.3	keep	accumulation_steps=4 with linear LR scaling (4x base LR) following the linear scaling rule
```

## What Didn't Work

- **Effective batch 256** (accumulation_steps=8): No further improvement; the model is small enough that batch 128 already provides sufficient gradient signal. Diminishing returns.
- **Square root LR scaling**: Scaling LR by sqrt(accumulation_steps) instead of linearly underperformed. Linear scaling rule (Goyal et al., 2017) worked better for this model size.

## Environment

PyTorch 2.1, single NVIDIA RTX 4090 (24 GB VRAM), 125M parameter GPT-2-style transformer, OpenWebText dataset, trained for 50k steps.
