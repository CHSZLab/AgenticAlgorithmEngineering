# Replacing hand-written secp256k1 BigInteger arithmetic with a curve library (Java Schnorr signing)

## Problem

A Java SDK for the Nostr protocol (BIP-340 Schnorr signatures over secp256k1, SHA-256 event ids, JSON event serialization, in-memory filter matching). The metric was the geometric mean of per-operation times over seven workloads: sign, verify, public key derivation, event id update (small and 200-tag event), JSON round trip, and matching a filter against 10,000 events. Baseline geometric mean: 579 us. The elliptic-curve code was a textbook affine double-and-add on `java.math.BigInteger`: 256 iterations, each with a modular inversion done as `modPow(p-2, p)`. Sign took 29 ms, verify 14 ms, public key derivation 4.7 ms; everything else was in the microseconds, so the curve code was three orders of magnitude above the rest.

## What Worked

1. **Use the curve implementation that is already on the classpath (about 100x).** BouncyCastle was already a dependency. Its custom `secp256k1` curve (`CustomNamedCurves.getByName("secp256k1")`) uses Jacobian coordinates, so a scalar multiplication costs one inversion at the end instead of one per step. Keep the project's own `Point` type as the public API and convert at the boundary (`curve.createPoint(x, y)` in, `normalize()` and the affine coordinates out). For the fixed generator use `FixedPointUtil.precompute(G)` once in a static initializer and `FixedPointCombMultiplier` for every `k*G`. Sign went from 29 ms to 0.4 ms, verify from 14 ms to 0.25 ms, public key derivation from 4.7 ms to 0.09 ms.
2. **Verify with one simultaneous two-scalar multiplication (verify -42%).** Schnorr verification needs `s*G - e*P`. Replacing two separate multiplications plus an addition with `ECAlgorithms.sumOfTwoMultiplies(G, s, P, n - e)` (GLV endomorphism plus Shamir's trick) took verify from 250 us to 146 us. I had predicted 25%. It beats the precomputed comb for `s*G` because the second multiplication shares the doublings. Sign ends with a self-verification, so it improved too.
3. **Do not re-derive what you already hold.** Sign lifted its own public key x-coordinate again in the self-check and recomputed `P.toBytes()` and `R.toBytes()` several times. Passing the known point (negated if its y is odd, because BIP-340 lifts to the even y) and caching the byte arrays gave sign -13%.
4. **Stream JSON instead of building a tree (update and JSON round trip about -22% in the first measurement, -29% to -44% against the final baseline).** The event id serialization built an `ArrayNode`, ran `ObjectMapper.valueToTree(tags)`, then wrote it as a string. Writing the array straight to a `JsonGenerator` over a `StringWriter` (with `gen.setCodec(mapper)` and `gen.writeObject(tag)` so the custom tag serializer still applies) removes a whole tree and gave byte-identical output. I predicted 40% and measured 22%, so the rest is Jackson's per-tag serializer lookup, not the tree.
5. **Single-pass filter predicate with hash sets (filter matching -75% in the first measurement, -64% against the final baseline).** `Predicate.and` chains, `List.contains`, and a `stream().filter().map().filter().anyMatch()` pipeline per tag filter per event were replaced by one lambda over precomputed `HashSet`s and a plain loop over the tags. I predicted 30%.

## Experiment Data (optional)

| Workload | Baseline | Best | Change |
|---|---|---|---|
| sign | 29,084 us | 313 us | 93x |
| verify | 14,125 us | 155 us | 91x |
| public key derivation | 4,720 us | 78 us | 61x |
| event id update, small | 2.5 us | 1.4 us | -44% |
| event id update, 200 tags | 66.4 us | 44.5 us | -33% |
| JSON round trip | 25.5 us | 18.1 us | -29% |
| filter over 10k events | 2,628 us | 951 us | -64% |
| geometric mean | 579 us | 63.5 us | 9.1x |

Six experiments, five kept, one discarded. The first three kept changes were tested in one multi-component run: each had its own commit and its own workloads, so the per-workload profile attributed each gain without separate runs.

## What Didn't Work (optional)

- **Replacing the BigInteger square root in `liftX` with BouncyCastle point decoding.** I assumed the 256-bit `modPow` was about a third of verify. Timed in isolation it was 19.3 us of about 150 us, and the replacement took 16.0 us, so it saved about 2%. The change was correct (differential test, below) but not worth its exception-based control flow. Lesson: time a suspected component on its own before building a hypothesis on a guessed share.
- **Going below the library.** Raw BouncyCastle fixed-base multiplication was 78 us, and the project's wrapper `Point.mul` (with BigInteger conversions) was 85 us. So the glue costs under 10%, and further wins would need custom precomputation tables, not tuning. That is where the loop stopped.
- **Dropping the self-verification at the end of sign.** It would have saved about half of sign time, but it is a fault-injection safeguard and was deliberately kept.

## Measurement Lessons

These cost more time than any optimization:
- **A fixed warmup count stops being valid after a big win.** 20 warmup iterations were fine at 30 ms per operation and badly under-warmed the same workload at 0.3 ms. After a large speedup, re-check warmup and iteration counts against the new per-operation time, and re-measure the reference under the changed harness.
- **On a loaded shared machine (load average about 10 on 12 threads) wall-clock medians moved by 20 to 40% on unchanged code.** Switching to thread CPU time (`ThreadMXBean.getCurrentThreadCpuTime`) and the minimum over 15 rounds, as the estimator for additive noise, made repeated runs agree to about 10%. Run a candidate and its predecessor alternately when the effect is near that band.
- **Confounding through composition.** Sign contains a verify, so a verify speedup also speeds up sign. To attribute a sign gain to a sign-only change, benchmark the commit before it in the same window.
- **Correctness safety net that carried the whole session:** a golden file of outputs (public keys for 100 keys, deterministic signatures, event ids and serialized-byte hashes for 16 events with escapes, emoji and 5,000-character content, JSON round trip) generated from the baseline, plus tamper checks (altered message, s, and R must fail), the official BIP-340 vectors, and a differential test of any rewritten function against the old implementation on 4,006 inputs including boundary values.

## Code Example (optional)

```java
// Point: BouncyCastle-backed arithmetic behind the existing BigInteger-based type
private static final X9ECParameters BC_PARAMS = CustomNamedCurves.getByName("secp256k1");
private static final ECCurve BC_CURVE = BC_PARAMS.getCurve();
private static final ECPoint BC_G = BC_PARAMS.getG();
private static final FixedPointCombMultiplier G_MULTIPLIER = new FixedPointCombMultiplier();
static { FixedPointUtil.precompute(BC_G); }

public static Point mul(Point P, BigInteger n) {
  if (n.signum() == 0) return null;                      // keeps the old "no point" contract
  ECPoint r = P.equals(G) ? G_MULTIPLIER.multiply(BC_G, n) : toBc(P).multiply(n);
  return fromBc(r);
}

public static Point mulSum(Point P, BigInteger a, Point Q, BigInteger b) {
  ECPoint p1 = P.equals(G) ? BC_G : toBc(P);
  ECPoint q1 = Q.equals(G) ? BC_G : toBc(Q);
  return fromBc(ECAlgorithms.sumOfTwoMultiplies(p1, a, q1, b));   // s*G + (n-e)*P in verify
}
```

## Environment (optional)

Java 21 (OpenJDK), BouncyCastle `bcprov-jdk18on` 1.81, Jackson 2.18 with the Blackbird module, SerialGC with a fixed 1 GB heap, 12 hardware threads on a shared, loaded machine. The curve technique transfers to any JVM code doing secp256k1 or other short-Weierstrass work with BigInteger (ECDSA, Schnorr, ECDH); the serialization and filter points transfer to any Jackson-based hot path.
