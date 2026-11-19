#import "BWObjects.h"
#if TARGET_OS_SIMULATOR && DEBUG
@interface BWCentral : NSObject
@property(nonatomic, weak) CBCentralManager *manager;
@property(atomic, weak) id<CBCentralManagerDelegate> delegate;
@property(atomic) CBManagerState state;
@property(atomic) BOOL scanning;
@property(nonatomic) dispatch_queue_t callbackQueue;
@property(nonatomic) BWRPC *rpc;
- (instancetype)initWithManager:(CBCentralManager *)manager
                       delegate:(id<CBCentralManagerDelegate>)delegate
                          queue:(dispatch_queue_t)queue;
- (void)scan:(NSArray<CBUUID *> *)services options:(NSDictionary *)options;
- (void)stopScan;
- (void)connect:(BWPeripheral *)peripheral;
- (void)cancel:(BWPeripheral *)peripheral;
- (NSArray *)retrieve:(NSArray<NSUUID *> *)identifiers;
- (void)discover:(BWPeripheral *)p services:(NSArray *)uuids;
- (void)characteristics:(BWPeripheral *)p service:(BWService *)service filter:(NSArray *)uuids;
- (void)descriptors:(BWPeripheral *)p characteristic:(BWCharacteristic *)characteristic;
- (void)read:(BWPeripheral *)p characteristic:(BWCharacteristic *)characteristic;
- (void)write:(BWPeripheral *)p
    characteristic:(BWCharacteristic *)characteristic
              data:(NSData *)data
              type:(CBCharacteristicWriteType)type;
- (void)notify:(BWPeripheral *)p
    characteristic:(BWCharacteristic *)characteristic
           enabled:(BOOL)enabled;
- (void)readRSSI:(BWPeripheral *)p;
- (void)readDescriptor:(BWPeripheral *)p descriptor:(BWDescriptor *)descriptor;
- (void)writeDescriptor:(BWPeripheral *)p descriptor:(BWDescriptor *)descriptor data:(NSData *)data;
@end
#endif
