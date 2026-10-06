// usage: node submit_message.mjs <topicId> <message>  -> {"sequenceNumber":N,"transactionId":"0.0.x@s.n"}
import { TopicMessageSubmitTransaction } from "@hashgraph/sdk";
import { makeClient } from "./client.mjs";

const [topicId, message] = process.argv.slice(2);
const client = makeClient();
try {
  const tx = await new TopicMessageSubmitTransaction({ topicId, message }).execute(client);
  const receipt = await tx.getReceipt(client);
  console.log(JSON.stringify({
    sequenceNumber: Number(receipt.topicSequenceNumber.toString()),
    transactionId: tx.transactionId.toString(),
  }));
} catch (e) {
  console.error(String(e));
  process.exitCode = 1;
} finally {
  client.close();
}
