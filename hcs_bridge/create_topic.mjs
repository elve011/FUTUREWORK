// usage: node create_topic.mjs <memo>   -> {"topicId":"0.0.x"}
import { TopicCreateTransaction } from "@hashgraph/sdk";
import { makeClient } from "./client.mjs";

const client = makeClient();
try {
  const tx = await new TopicCreateTransaction().setTopicMemo(process.argv[2] ?? "").execute(client);
  const receipt = await tx.getReceipt(client);
  console.log(JSON.stringify({ topicId: receipt.topicId.toString() }));
} catch (e) {
  console.error(String(e));
  process.exitCode = 1;
} finally {
  client.close();
}
