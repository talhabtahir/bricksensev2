import streamlit as st
from PIL import Image, ImageOps, ExifTags
import numpy as np
import tensorflow as tf
import cv2
from keras.models import Model
import matplotlib.pyplot as plt

@st.cache_resource
def load_model():
    try:
        model = tf.keras.models.load_model('170kmodelv3_version_cam_1.keras')
        return model
    except Exception as e:
        st.error(f"Failed to load model: {e}")
        return None

model = load_model()

def correct_orientation(image):
    try:
        if hasattr(image, '_getexif'):
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            exif = image._getexif()
            if exif is not None:
                orientation = exif.get(orientation, 1)
                if orientation == 3:
                    image = image.rotate(180, expand=True)
                elif orientation == 6:
                    image = image.rotate(270, expand=True)
                elif orientation == 8:
                    image = image.rotate(90, expand=True)
    except Exception as e:
        st.error(f"Error correcting orientation: {e}")
    return image

def import_and_predict(image_data, model, layer_index=11):
    try:
        # Get original image size
        original_size = image_data.size  # (width, height)
        original_width, original_height = original_size
        size = (224, 224)  # Model input size

        # Resize the image for model prediction
        image_resized = image_data.convert("RGB")
        image_resized = ImageOps.fit(image_resized, size, Image.LANCZOS)
        img = np.asarray(image_resized).astype(np.float32) / 255.0
        img_reshape = img[np.newaxis, ...]

        # Get predictions from the model
        custom_model = Model(inputs=model.inputs, 
                             outputs=(model.layers[layer_index].output, model.layers[-1].output))
        layer_output, pred_vec = custom_model.predict(img_reshape)

        # Get the predicted class and confidence
        pred = np.argmax(pred_vec)

        # Extract the feature map output
        layer_output = np.squeeze(layer_output)  # Shape varies based on the layer

        # Average across the depth dimension to generate the heatmap
        heat_map = np.mean(layer_output, axis=-1)  # Shape depends on the layer

        # Normalize the heatmap between 0 and 1 for better visualization
        heat_map = np.maximum(heat_map, 0)  # ReLU to eliminate negative values
        heat_map /= np.max(heat_map)  # Normalize to 0-1

        # Resize heatmap to the size of the resized image (224, 224)
        heatmap_resized = cv2.resize(heat_map, size, interpolation=cv2.INTER_LINEAR)

        # Threshold the heatmap to get regions of interest
        _, thresh_map = cv2.threshold(np.uint8(255 * heatmap_resized), 127, 255, cv2.THRESH_BINARY)

        # Find contours in the thresholded heatmap
        contours, _ = cv2.findContours(thresh_map, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Convert original image to numpy array (for contour drawing)
        original_img_np = np.array(image_data)

        # Ensure the original image is in 3 channels (RGB) for contour drawing
        if len(original_img_np.shape) == 2:  # If grayscale, convert to RGB
            original_img_np = cv2.cvtColor(original_img_np, cv2.COLOR_GRAY2RGB)

        # Draw contours on the original image, but scale contours to the original size
        original_img_bgr = cv2.cvtColor(original_img_np, cv2.COLOR_RGB2BGR)

        # Scale contours back to original image size
        scale_x = original_width / size[0]
        scale_y = original_height / size[1]
        
        # Adjust the scaling more precisely based on aspect ratio consistency
        def scale_contours(contours, scale_x, scale_y):
            scaled_contours = []
            for contour in contours:
                scaled_contour = np.array([[int(point[0][0] * scale_x), int(point[0][1] * scale_y)] for point in contour])
                scaled_contours.append(scaled_contour)
            return scaled_contours

        scaled_contours = scale_contours(contours, scale_x, scale_y)

        # Draw scaled contours on the original image (in blue BGR: (255, 0, 0))
        cv2.drawContours(original_img_bgr, scaled_contours, -1, (255, 0, 0), 2)  # Blue contours

        # Convert the image back to RGB
        contours_img_rgb = cv2.cvtColor(original_img_bgr, cv2.COLOR_BGR2RGB)

        # Convert to a PIL Image for display in Streamlit
        contours_pil = Image.fromarray(contours_img_rgb)

        return pred_vec, contours_pil
    except Exception as e:
        st.error(f"An error occurred during prediction: {e}")
        return None, None

# Main area for image upload
file = st.file_uploader("Please upload an image of the brick wall", type=["jpg", "png", "jpeg", "bmp", "tiff", "webp"])

# Check if a file was uploaded
if file is None:
    st.info("Please upload an image file to start the detection.")
else:
    with st.spinner("Processing image..."):
        try:
            # Try to open the uploaded image using PIL
            image = Image.open(file)
            if image is None:
                raise ValueError("Uploaded file is not a valid image.")

            # Correct the orientation if necessary
            image = correct_orientation(image)

            # Ensure the image format is valid
            if image.format not in ["JPEG", "PNG", "BMP", "TIFF", "WEBP"]:
                raise ValueError("Unsupported image format. Please upload JPG, PNG, BMP, TIFF, or WEBP files.")

            # Display the uploaded image and the contours side by side
            col1, col2 = st.columns(2)

            with col1:
                st.image(image, caption="Uploaded Image", use_column_width=True)

            # Add a slider for selecting the layer index dynamically
            layer_index = st.slider("Select layer index for feature extraction", min_value=6, max_value=len(model.layers)-4, value=10)

            # Perform prediction
            predictions, contours_pil = import_and_predict(image, model, layer_index)
            if predictions is not None:
                predicted_class = np.argmax(predictions)
                prediction_percentages = predictions[0] * 100

                st.write(f"**Prediction Percentages:**")
                st.write(f"Normal Wall: {prediction_percentages[0]:.2f}%")
                st.write(f"Cracked Wall: {prediction_percentages[1]:.2f}%")
                st.write(f"Not a Wall: {prediction_percentages[2]:.2f}%")

                with col2:
                    if predicted_class == 1:
                        st.image(contours_pil, caption="Cracks Localization", use_column_width=True)
                    else:
                        st.warning(f"Contours are not applicable. This is not a cracked wall.")
                
                # Display prediction result
                if predicted_class == 0:
                    st.success(f"✅ This is a normal brick wall.")
                elif predicted_class == 1:
                    st.error(f"❌ This wall is a cracked brick wall.")
                elif predicted_class == 2:
                    st.warning(f"⚠️ This is not a brick wall.")
                else:
                    st.error(f"❓ Unknown prediction result: {predicted_class}")
        except Exception as e:
            st.error(f"Error processing the uploaded image: {e}")
