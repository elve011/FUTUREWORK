import { Client, PrivateKey } from "@hashgraph/sdk";

// HEDERA_KEY_TYPE: der (default, 302e...) | ecdsa (raw 32-byte hex, portal "HEX Encoded") | ed25519 (raw hex)
export function makeClient() {
  const id = process.env.HEDERA_OPERATOR_ID;
  const key = process.env.HEDERA_OPERATOR_KEY;
  if (!id || !key) throw new Error("HEDERA_OPERATOR_ID / HEDERA_OPERATOR_KEY not set");
  const type = (process.env.HEDERA_KEY_TYPE || "der").toLowerCase();
  const pk = type === "ecdsa" ? PrivateKey.fromStringECDSA(key)
           : type === "ed25519" ? PrivateKey.fromStringED25519(key)
           : PrivateKey.fromString(key);
  return Client.forTestnet().setOperator(id, pk);
}
