#import "BWRPC.h"
#import <CoreBluetooth/CoreBluetooth.h>
#if TARGET_OS_SIMULATOR && DEBUG
@class BWCentral;
@interface BWPeripheral : CBPeripheral
@property(atomic, weak) id<CBPeripheralDelegate> bwDelegate;
@property(atomic) NSUUID *bwIdentifier;
@property(atomic, copy) NSString *bwName;
@property(atomic) CBPeripheralState bwState;
@property(atomic, copy) NSArray<CBService *> *bwServices;
@property(atomic) BOOL bwCanSend;
@property(atomic) NSUInteger attMTU;
@property(nonatomic, weak) BWCentral *owner;
@property(nonatomic) NSString *address;
@property(nonatomic) NSString *connectionID;
@property(atomic) NSUInteger epoch;
@property(nonatomic) NSArray *schema;
@property(nonatomic) NSMutableArray *allServices;
@property(nonatomic) NSMutableDictionary *characteristics;
@property(nonatomic) NSMutableArray<dispatch_block_t> *operations;
@property(nonatomic) BOOL busy;
- (instancetype)initBWWithAddress:(NSString *)address name:(NSString *)name;
@end
@interface BWService : CBService
@property(nonatomic) NSString *remoteID;
@property(nonatomic) CBUUID *bwUUID;
@property(nonatomic, weak) BWPeripheral *bwPeripheral;
@property(atomic, copy) NSArray *bwCharacteristics;
@property(nonatomic) NSArray *allCharacteristics;
- (instancetype)initBWWithDefinition:(NSDictionary *)definition
                          peripheral:(BWPeripheral *)peripheral;
@end
@interface BWCharacteristic : CBCharacteristic
@property(nonatomic) NSString *remoteID;
@property(nonatomic) CBUUID *bwUUID;
@property(nonatomic, weak) BWService *bwService;
@property(nonatomic) CBCharacteristicProperties bwProperties;
@property(atomic, copy) NSData *bwValue;
@property(atomic) BOOL bwNotifying;
@property(atomic, copy) NSArray *bwDescriptors;
@property(nonatomic) NSArray *allDescriptors;
- (instancetype)initBWWithDefinition:(NSDictionary *)definition service:(BWService *)service;
@end
@interface BWDescriptor : CBDescriptor
@property(nonatomic) NSString *remoteID;
@property(nonatomic) CBUUID *bwUUID;
@property(nonatomic, weak) BWCharacteristic *bwCharacteristic;
@property(atomic) id bwValue;
- (instancetype)initBWWithDefinition:(NSDictionary *)definition
                      characteristic:(BWCharacteristic *)characteristic;
@end
#endif
