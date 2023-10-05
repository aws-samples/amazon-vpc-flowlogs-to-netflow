import json
import boto3
import socket   
import struct
import time
import datetime
import gzip
import tempfile

s3_client = boto3.client("s3")
netflow_receiver_address = "x.x.x.x" # Change this to the address of your NetFlow Receiver
netflow_receiver_port = 2055

#------------------------------------------------------------------------------------------------------
# Builds the netflow v5 header packet
#------------------------------------------------------------------------------------------------------
def v5_flow_header(numFlows=1):
    
    # Change starttime to something else. If this gets too large for a 32bit int then the struct.pack line will error
    starttime = (datetime.datetime(2023, 9, 23, 0, 0)).timestamp()
    now = time.time()

    version = 5
    count = numFlows                                            # Number of flow records in this packet
    uptime = int(now - starttime) * 1000                        # System uptime in milliseconds
    timestamp = int(time.time())                                # Current timestamp
    unix_secs = timestamp                                       # Seconds since January 1, 1970 (UNIX time)
    unix_nsecs = int(time.time_ns() % 1_000_000_000)            # Nanoseconds part of the timestamp
    flow_sequence = 1                                           # Flow sequence counter
    engine_type = 188                                           # Type of flow-switching engine
    engine_id = 0                                               # ID of the flow-switching engine
    sampling_interval = 1                                       # Sampling interval

    print("Header [{0}], [{1}], [{2}], [{3}], [{4}], [{5}], [{6}], [{7}], [{8}]".format( 
                                version,
                                count,
                                uptime,
                                unix_secs,
                                unix_nsecs,
                                flow_sequence,
                                engine_type,
                                engine_id,
                                sampling_interval))

    # Create the NetFlow v5 header packet
    header_packet = struct.pack('!HHIIIIBBH',
                                version,
                                count,
                                uptime,
                                unix_secs,
                                unix_nsecs,
                                flow_sequence,
                                engine_type,
                                engine_id,
                                sampling_interval)
    
    return header_packet
    
    
#------------------------------------------------------------------------------------------------------
# Builds the netflow v5 record packet
#------------------------------------------------------------------------------------------------------    
def v5_flow_record(srcaddr, dstaddr, srcport, dstport, protocol, tcpflags, packets, bytes, start, end):
    
    srcaddr_bytes = socket.inet_pton(socket.AF_INET, srcaddr)
    dstaddr_bytes = socket.inet_pton(socket.AF_INET, dstaddr)
    
    netflow_packet = struct.pack("!4s4s4sHHIIIIHHsBBsHHBB2s",
                        srcaddr_bytes,
                        dstaddr_bytes,
                        b'\x00' * 4,
                        1,
                        1,
                        packets,
                        bytes,
                        start,
                        end,
                        srcport,
                        dstport,
                        b'\x00',
                        tcpflags,
                        protocol,
                        b'\x00',
                        0,
                        0,
                        32,
                        32,
                        b'\x00' * 2)
                            
    return netflow_packet
    
#------------------------------------------------------------------------------------------------------
# Processes the VPC flow log and converts it into a Netflow v5 packet
#------------------------------------------------------------------------------------------------------
def load_vpc_flow_log(vpc_flow_log_fileName):
    
    #------------------------------------------------------------------------------------------------------
    # Setup a UDP connection to our NetFlow receiver on the address and port specified above
    # If we fail we just return False
    #------------------------------------------------------------------------------------------------------
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((netflow_receiver_address, netflow_receiver_port))
    except:
        print("ERROR: Couldn't connect to NetFlow receiver {0}:{1}".format(netflow_receiver_address, netflow_receiver_port))
        return False
    
    #------------------------------------------------------------------------------------------------------
    # Is the file compressed? If we use VPC Flow logs to S3 then yes it will be
    # If we're using Kinesis Firehose to S3 then it might not be
    # I make the assumption that the file IS compressed. You will need to change the logic if it's not
    #------------------------------------------------------------------------------------------------------
    lineNumber = 1
    records = bytes()
    
    # lets gunzip it
    with gzip.open(vpc_flow_log_fileName, 'rt') as f:
        
        # Crude for loop to run through each line in the VPC FlowLog file
        for line in f:
            if "VERSION" in line or "SKIPDATA" in line or "NODATA" in line:
                continue

            # Instead of trying to import potential JSON from KFH we just remove it, should work for either Direct S3 or KFH
            log = line.replace('{"message":"', '').replace('"}', '').strip().split(' ')

            # Extract log fields
            # NOTE: if you change the VPC Flow Log format then you need to update this code to match
            version         = log[0]
            account_id      = log[1]
            interface_id    = log[2]
            src_addr        = log[3]
            dst_addr        = log[4]
            src_port        = log[5]
            dst_port        = log[6]
            protocol        = log[7]
            packets         = log[8]
            nbytes          = log[9]
            start           = log[10]
            end             = log[11]
            action          = log[12]
            log_status      = log[13]
            tcpflags        = log[14]
            pkt_srcaddr     = log[15]
            pkt_dstaddr     = log[16]
            flow_direction  = log[17]

            # We need to remember that if our traffic VPC flow log is attached to an ENI then the source address will be that of the ENI
            # Example: We have TGW setup and the attachment sits in a /28 seperate subnet as per best practise
            # the default route is out of another subnet on to IGW/NGW etc. 
            # If the VPC Flow Log is configured on the subnet of the TGW attachment then the src_addr will be the ENI of the TGW Attachment.
            # You need to use the pkt_srcaddr value instead
            
            record = v5_flow_record(pkt_srcaddr, 
                                    pkt_dstaddr, 
                                    int(src_port), 
                                    int(dst_port), 
                                    int(protocol), 
                                    int(tcpflags), 
                                    int(packets), 
                                    int(nbytes), 
                                    int(start), 
                                    int(end))

            
            stime = datetime.datetime.fromtimestamp(int(start))
            print("Sending packet | {8} {0:>15}:{1:<5} ({9:>15}) --> {2:>15}:{3:<5} ({10:>15}) [{4:>2}] Bytes: {5:>5} Packets: {6:>3}, Flags: {7}".format(src_addr, src_port, dst_addr, dst_port, protocol, nbytes, packets, tcpflags, stime.strftime('%Y-%m-%d %H:%M:%S'), pkt_srcaddr, pkt_dstaddr))
            
            
            # NetFlow v5 packets can only have 30 flows + header. Anymore and they need to be split into sperate packets
            if lineNumber < 30:
                records = records + record
                lineNumber += 1
            elif lineNumber >= 30:
                whole_packet = v5_flow_header(30) + records
                sock.send(whole_packet)
                lineNumber = 1
                records = bytes()
                
        if len(records) > 0:
            whole_packet = v5_flow_header(lineNumber - 1) + records
            sock.send(whole_packet)
            
    sock.close()
#------------------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------------------
def lambda_handler(event, context):
    
    bucketName = event['Records'][0]['s3']['bucket']['name']
    fileName = event['Records'][0]['s3']['object']['key']
    
    # We use tempfile to generate a random temp file, mitigates against
    # https://cwe.mitre.org/data/definitions/377.html
    localFileName = tempfile.NamedTemporaryFile(suffix='.gz').name
    
    response = s3_client.download_file(bucketName, fileName, localFileName)
    s3_client.delete_object(Bucket=bucketName, Key=fileName)
    
    load_vpc_flow_log(localFileName)
    
    return {
        'statusCode': 200,
        'body': json.dumps('OK')
    }
