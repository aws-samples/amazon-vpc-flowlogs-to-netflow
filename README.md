# Amazon VPC FlowLogs to a NetFlow v5 Receiver

This repository shows an example of [AWS Lambda](https://aws.amazon.com/lambda/) python code that reads [Amazon VPC FlowLogs](https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs.html) and converts them into NetFlow v5 compatible packets. 

**This code is not production ready. It's an example of what is possible.**

## Usage

1. Configure VPC Flow Logs in the correct format (see VPC Flow Log Format [below](#vpc-flowlog-format))
2. Configure VPC Flow Logs to store the logs as a GZIP compressed file stored in a [Amazon Simple Storage Service (Amazon S3)](https://aws.amazon.com/s3/) bucket. You can either save the flow logs directly to Amazon S3 (~10 minute delay) or push them through a [Amazon Kinesis Data Firehose](https://aws.amazon.com/kinesis/data-firehose/) stream (~1 minute delay)
3. Deploy the Lambda code. 
   - I tested it using Python 3.10
   - Review the amount of memory allocated to the Lambda function. You may need to increase this depending on how long the function takes to process your flow log files
   - Review the timeout setting for the Lambda function and increase if needed
   - Ensure that the Lambda function is deployed into a VPC that can reach your NetFlow v5 receiver
   - Ensure that the Lambda function has the right permissions to access the S3 bucket
   - Update the code and fill in your details for the following global variables:
     - ```netflow_receiver_address``` - set to the IP address or DNS name of your Netflow v5 receiver
     - ```netflow_receiver_port``` - set to the port used by your Netflow v5 receiver
4. Configure a trigger mechanism to call your Lambda function. I used [S3 event notifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/enable-event-notifications.html). I filtered my notifications to only notify when a specific folder receives a PUT request for files ending .gz,  now when the bucket is updated with a new log file it triggers my Lambda function and in the event data it also sends the details of the S3 bucket and file that was added.
   - If you choose another mechanism then you will need to change the Lambda code appropriately

### VPC FlowLog Format

I am using a [custom VPC FlowLog format](https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs.html#flow-log-records). This is needed as the NetFlow packets require some extra fields:
- TCP Flags
- pkt_srcaddr
- pkt_dstaddr

The last two options are important because flow logs capture traffic flowing to and from interfaces. Depending on how your network infrastructure is configured means that the default source and destination fields might show interface addresses for other services. For example a Transit Gateway Attachment interface or the interface of a NAT Gateway. This would lead to an inconsistent experience when monitoring traffic flows. This is where the pkt_srcaddr and the pkt_dstaddr come in. These fields contain the original source/destination address of the packet.

The format I've used looks like this:

```${version} ${account-id} ${interface-id} ${srcaddr} ${dstaddr} ${srcport} ${dstport} ${protocol} ${packets} ${bytes} ${start} ${end} ${action} ${log-status} ${tcp-flags} ${pkt-srcaddr} ${pkt-dstaddr} ${flow-direction}```

If you change the format then the code will need to be altered to match.

## Known Issues/Limitations

1. This code was designed and tested against the NetFlow v5 format. It requires updating to work with the later formats.
2. This code has little to no error handling, it's just proof of concept code. You will need to add in some error handling.
3. The NetFlow flowsequence number is currently always set to 1. This works but isn't ideal. One method to fix this would be to send the S3 event notifications to a SQS FIFO queue. The SQS queue would empty at a rate of 1, calling the Lambda function. The Lambda function would be updated to store the current flowsequence somewhere (DynamoDB?) so that it can be updated correctly. (flowsequence is a 32-bit integer, which is 4,294,967,295 (2^32 - 1) in size so it'll need to be reset).

## Security

Ensure the IAM roles used by the Lambda function are as restrictive as possible.

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## Author

[Gareth Hastings](https://www.linkedin.com/in/gareth-hastings-8482aa43/)

## License

This same code is licensed under the MIT-0 License. See the LICENSE file.

